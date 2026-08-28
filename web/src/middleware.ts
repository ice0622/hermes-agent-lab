import { NextResponse, type NextRequest } from "next/server";

/**
 * Basic 認証。**未設定なら開けない。**
 *
 * Hobby プランでは Vercel Authentication が本番デプロイに使えず（Password Protection は Pro）、
 * `<project>.vercel.app` は素通しになる。体重とトレーニング記録が誰でも読める状態は許容できないので、
 * ここで閉じる。パスワード未設定のときは 503 を返す — 開いたまま動くより、動かないほうがよい。
 *
 * ローカル（VERCEL 未設定）は素通し。
 */
const REALM = "hermes-health";

export function middleware(req: NextRequest) {
  if (!process.env.VERCEL) return NextResponse.next();

  const pass = process.env.DASHBOARD_PASSWORD;
  if (!pass) {
    return new NextResponse(
      "保護が未設定のため閉じています。\n" +
        "Vercel に DASHBOARD_PASSWORD を入れてください（任意で DASHBOARD_USER）。\n",
      { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } },
    );
  }

  const header = req.headers.get("authorization");
  if (header?.startsWith("Basic ")) {
    let decoded = "";
    try {
      decoded = atob(header.slice(6));
    } catch {
      decoded = "";
    }
    const i = decoded.indexOf(":");
    const user = i < 0 ? "" : decoded.slice(0, i);
    const given = i < 0 ? "" : decoded.slice(i + 1);
    const wantUser = process.env.DASHBOARD_USER;
    const userOk = !wantUser || equal(user, wantUser);
    if (userOk && equal(given, pass)) return NextResponse.next();
  }

  return new NextResponse("Unauthorized", {
    status: 401,
    headers: {
      "www-authenticate": `Basic realm="${REALM}", charset="UTF-8"`,
      "content-type": "text/plain; charset=utf-8",
    },
  });
}

/** 長さは漏れるが内容は漏らさない比較。Edge ランタイムに timingSafeEqual が無いので自前。 */
function equal(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export const config = {
  matcher: "/((?!_next/static|_next/image|favicon\\.ico).*)",
};

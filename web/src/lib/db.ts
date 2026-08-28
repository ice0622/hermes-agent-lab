import { createClient, type Client, type InArgs } from "@libsql/client";

/**
 * DB への口はここだけ。
 *
 * ローカルは `file:` で WSL2 の health.db を直接読み、本番は Turso の `libsql://` を読む。
 * 同じ SQLite 方言なのでクエリは1つで済み、切り替えは DATABASE_URL だけになる。
 * 書き込みは一切しない（記録側は health CLI の責任。docs/plan.md T22）。
 */
let cached: Client | undefined;

/**
 * DB に繋げる状態か。
 *
 * Vercel 上では DATABASE_URL が Turso を指していないと何も読めない。未設定のまま
 * 500 を返すより、何が足りないかを画面に出したい（page.tsx がこれを見て分岐する）。
 * `file:` はローカル専用なので、本番で残っていたら未設定と同じ扱いにする。
 */
export function configured(): { ok: boolean; reason?: string } {
  const url = process.env.DATABASE_URL;
  if (!url) return { ok: false, reason: "DATABASE_URL が未設定" };
  if (url.startsWith("file:") && process.env.VERCEL) {
    return { ok: false, reason: `DATABASE_URL がローカルのファイルを指している（${url}）` };
  }
  return { ok: true };
}

function client(): Client {
  if (cached) return cached;
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error(
      "DATABASE_URL が未設定です。web/.env.local を作ってください（web/.env.example を参照）。",
    );
  }
  cached = createClient({
    url,
    // Turso のときだけ必要。file: では未設定でよい
    authToken: process.env.DATABASE_AUTH_TOKEN,
  });
  return cached;
}

export async function all<T>(sql: string, args: InArgs = []): Promise<T[]> {
  const rs = await client().execute({ sql, args });
  return rs.rows as unknown as T[];
}

export async function one<T>(sql: string, args: InArgs = []): Promise<T | null> {
  const rows = await all<T>(sql, args);
  return rows[0] ?? null;
}

/** DB に繋がっていないときに出す。何をすれば動くのかだけを書く。 */
export default function Setup({ reason }: { reason?: string }) {
  return (
    <main className="wrap">
      <h1 className="rise">筋トレ</h1>
      <p className="sub rise" style={{ ["--i" as string]: 1 }}>
        データベースに繋がっていない
      </p>

      <div className="warn" style={{ marginTop: 28 }}>
        <b>{reason ?? "DATABASE_URL が未設定"}</b>
        <br />
        記録は WSL2 上の SQLite にある。Vercel からは読めないので、Turso（libSQL）を経由させる。
      </div>

      <h2>残っている手順</h2>
      <ol className="steps">
        <li>
          <b>Turso で DB を作る</b>
          <span>
            turso.tech でサインアップして DB を1つ作る。CLI は不要で、ダッシュボードの
            <em> Database URL</em> と <em>auth token</em> をコピーするだけでよい。
          </span>
        </li>
        <li>
          <b>Vercel に環境変数を入れる</b>
          <span>
            <code>DATABASE_URL=libsql://…</code> と <code>DATABASE_AUTH_TOKEN=…</code>
          </span>
        </li>
        <li>
          <b>ローカルのデータを押し上げる</b>
          <span>
            <code>node scripts/push-turso.mjs</code>
            {" — "}ローカルの SQLite が正典のまま、片方向で複製する。記録はネットワーク不要のままになる。
          </span>
        </li>
      </ol>

      <p className="foot">
        ローカルで見るだけなら <code>web/.env.local</code> に{" "}
        <code>DATABASE_URL=file:$HOME/health/health.db</code> を書いて <code>npm run dev</code>。
      </p>
    </main>
  );
}

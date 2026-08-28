/**
 * ローカルの health.db を Turso に片方向で複製する。
 *
 *   node scripts/push-turso.mjs
 *
 * **ローカルの SQLite が正典。** Turso はその読み取り用の複製にすぎない。
 * 記録側（health CLI）は sqlite3 のまま一切変えないので、ネットワークが無くても
 * 記録は止まらない（docs/plan.md「記録が止まるのが最悪」）。
 *
 * データは160KB程度しかないので、賢い差分同期はやらない。全行を消して入れ直す。
 * 差分の取り違えでデータが欠けるより、毎回全部送るほうが安い。
 *
 * 環境変数（web/.env.local から読む）:
 *   LOCAL_DB              既定 file:$HOME/health/health.db
 *   DATABASE_URL          libsql://<name>-<org>.turso.io
 *   DATABASE_AUTH_TOKEN   turso のトークン
 *
 * 複製先は `--to <url>` で上書きできる。Turso に向ける前に、一時ファイルへ複製して
 * 結果を確かめるのに使う:
 *
 *   node scripts/push-turso.mjs --to file:/tmp/copy.db
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createClient } from "@libsql/client";

const HERE = dirname(fileURLToPath(import.meta.url));
const SCHEMA = resolve(HERE, "../../skills/health/db/schema.sql");

/** 親→子の順。INSERT はこの順、DELETE は逆順で流す。 */
const TABLES = ["exercises", "foods", "routines", "sets", "meals", "body", "targets", "plans"];
const CHUNK = 200;

loadEnv(resolve(HERE, "../.env.local"));

const localUrl = process.env.LOCAL_DB ?? `file:${process.env.HOME}/health/health.db`;
const override = argValue("--to");
const remoteUrl = override ?? process.env.DATABASE_URL;
const authToken = process.env.DATABASE_AUTH_TOKEN;

if (!remoteUrl) fail("複製先が指定されていません。DATABASE_URL か --to <url> が必要です。");
if (!override) {
  if (remoteUrl.startsWith("file:")) {
    fail("DATABASE_URL が Turso を指していません。libsql://… を web/.env.local に入れてください。");
  }
  if (!authToken) fail("DATABASE_AUTH_TOKEN が未設定です。");
}

console.log(`${localUrl}\n  → ${remoteUrl}${override ? "  （--to で上書き）" : ""}\n`);

const local = createClient({ url: localUrl });
const remote = createClient({
  url: remoteUrl,
  // file: の複製先にトークンを渡すと弾かれる
  authToken: remoteUrl.startsWith("file:") ? undefined : authToken,
});

// ---------------------------------------------------------------- スキーマ
// PRAGMA は HTTP 経由の libSQL では通らないので落とす。残りは IF NOT EXISTS なので何度でも流せる。
const ddl = readFileSync(SCHEMA, "utf8")
  .split("\n")
  .filter((l) => !/^\s*PRAGMA\b/i.test(l))
  .join("\n")
  .split(";")
  .map((s) => s.replace(/^\s*--.*$/gm, "").trim())
  .filter(Boolean);

console.log(`スキーマ: ${ddl.length} 文を適用`);
for (const sql of ddl) {
  try {
    await remote.execute(sql);
  } catch (e) {
    fail(`スキーマの適用に失敗:\n  ${sql.slice(0, 120)}\n  ${e.message}`);
  }
}

// ---------------------------------------------------------------- データ
for (const t of [...TABLES].reverse()) {
  await remote.execute(`DELETE FROM ${t}`);
}
console.log("送信先を空にした");

let total = 0;
for (const table of TABLES) {
  const cols = (await local.execute(`PRAGMA table_info(${table})`)).rows.map((r) => r.name);
  const rows = (await local.execute(`SELECT ${cols.join(", ")} FROM ${table}`)).rows;
  const sql = `INSERT INTO ${table} (${cols.join(", ")}) VALUES (${cols.map(() => "?").join(", ")})`;

  for (let i = 0; i < rows.length; i += CHUNK) {
    await remote.batch(
      rows.slice(i, i + CHUNK).map((r) => ({ sql, args: cols.map((c) => r[c]) })),
      "write",
    );
  }
  total += rows.length;
  console.log(`  ${table.padEnd(10)} ${String(rows.length).padStart(5)} 行`);
}

// ---------------------------------------------------------------- 照合
console.log("\n照合:");
let mismatch = 0;
for (const t of TABLES) {
  const a = Number((await local.execute(`SELECT COUNT(*) n FROM ${t}`)).rows[0].n);
  const b = Number((await remote.execute(`SELECT COUNT(*) n FROM ${t}`)).rows[0].n);
  if (a !== b) mismatch++;
  console.log(`  ${t.padEnd(10)} ローカル ${String(a).padStart(5)} / 送信先 ${String(b).padStart(5)}` +
    (a === b ? "  一致" : "  ★ 不一致"));
}
console.log(mismatch ? `\n${mismatch} テーブルが不一致。` : `\n${total} 行、全テーブル一致。`);
process.exit(mismatch ? 1 : 0);

// ---------------------------------------------------------------- 小物

/** .env.local を読む。Next.js の外で動かすので dotenv は入れず自前で拾う。 */
function loadEnv(path) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch {
    return;
  }
  for (const line of text.split("\n")) {
    const m = /^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/.exec(line);
    if (!m) continue;
    const v = m[2].trim().replace(/^["']|["']$/g, "");
    if (!(m[1] in process.env)) process.env[m[1]] = v;
  }
}

function argValue(flag) {
  const i = process.argv.indexOf(flag);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

function fail(msg) {
  console.error(msg);
  process.exit(1);
}

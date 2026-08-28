# web — 筋トレダッシュボード

`health.db` を**読むだけ**の Next.js アプリ。記録も計算も Python 側の責任で、ここは表示に専念する
（`docs/plan.md` T22「書き込み側は一切変えない」）。

## 何を見せるか

体脂肪率が1件も入っていないので**筋肉量は直接測れない**。代理指標を2本立てで出す。

| セクション | 何を答えるか |
|---|---|
| 次のセッション | `lib/train.py` が組んだメニュー。重量の根拠つき |
| 強くなっているか | 種目ごとの推定1RM（Epley）と自己記録の鮮度 |
| 積み上げているか | 月 × 部位の挙上量。前半/後半の比較 |
| 続いているか | 月ごとのセッション日数 |
| 体重 | 実測と移動平均、そして体組成が空であることの明示 |

## ローカルで動かす

```bash
cp .env.example .env.local     # DATABASE_URL を自分のパスに直す
npm install
npm run dev                    # http://localhost:3000
```

`DATABASE_URL` は `file:` と `libsql://` の両方を受ける。`src/lib/db.ts` がその1点だけを見ている。

## 本番（Turso）

```bash
DATABASE_URL=libsql://<name>-<org>.turso.io
DATABASE_AUTH_TOKEN=<turso db tokens create <name>>
```

**ローカルの SQLite が正典**で、Turso はその複製。記録はネットワーク不要のまま
（`docs/plan.md`「記録が止まるのが最悪」）で、片方向で押し上げる。

## メニューの再計算

`plans` テーブルは `lib/train.py` の `materialize()` が全行置き換えで書く。
`health` CLI が筋トレを記録・取り消し・取り込みした時点で自動で走る。手で回すなら:

```bash
python3 ../skills/health/bin/health plan
```

**規則の実装は `train.py` だけに置く。**ここで作り直すと「3セット揃うまで上げない」が
2箇所に分かれて必ずずれる。

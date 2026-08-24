# 健康管理エージェント

仕様: `docs/spec/health-agent.md` / 実装計画: `docs/plan.md`

**フェーズ0（現在）は Hermes も API キーも不要。** CLI と SQLite だけで動く。
LLM が必要なのは「未知食品の栄養価」と「買い物指示」の2箇所だけで、それはフェーズ1。

## セットアップ

```bash
# DB を作ってマスタを入れる（既定: ~/health/health.db）
./skills/health/bin/health init

# 手書き記録1年分を投入。初日からグラフが出る状態にする
./skills/health/bin/health import
```

DB の場所は環境変数 `HEALTH_DB` で変えられる。

```bash
export HEALTH_DB=/tmp/test/health.db   # 試すとき
```

PATH に入れておくと楽。

```bash
ln -sf "$PWD/skills/health/bin/health" ~/.local/bin/health
```

## 記録

```bash
health t                      久しぶりの分割のメニューを出す
health t push                 分割を指定
health 1 60 8,8,7             メニューの番号で種目を指定
health bp 60 8,8,7            種目コードで指定（同一重量 × 8/8/7）
health bp 60x8,60x8,55x7      セットごとに重量が違う場合
health pu 5,4,3               自重種目
health w 64.2                 体重
health w 64.2 15.3            体重 + 体脂肪率
health m サラダチキン, おにぎり*2   食事（カンマ区切り）
health m 12:30 牛丼            時刻を明示
health undo                   直前の記録を取り消す
health last                   直近の記録を確認
```

数量は `*2` `x2` `×2` `:2` `2個` `2本` `2枚` `2杯` などに対応する。

## 確認と診断

```bash
health today                  今日の摂取と残り
health check                  問題点と次のアクション
health check --apply          提案された目標カロリーの変更を適用
```

## 設計上の約束

- **記録は止めない。** マスタに無い食品でも栄養価 0 の「未知」として記録し、
  `health check` が後で報告する。入力がエラーで弾かれると、その日から記録をやめる
- **筋トレ・体重・既知食品の記録に LLM を使わない。** 正規表現とマスタ参照だけ。
  `bp 60 8,8,7` は自然言語より速く打てて、しかも無料
- **診断は必ず「次のアクション」を1つ付ける。** 問題の指摘だけでは行動が変わらない
- **記録が無いときは他の分析を出さない。** 前提の無い分析はノイズになる。
  記録が続いていないときは、目標ではなく**入力形式（手段）を疑う**
- **目標値は固定しない。** 体重の週平均で毎週補正する（`health check`）。
  TDEE の推定式には ±10% の誤差があるため

## 構成

```
skills/health/
├── bin/health              CLI エントリ
├── db/
│   ├── schema.sql          7テーブル + ビュー4つ
│   ├── seed_exercises.sql  種目39・ルーティン15・初期目標
│   └── seed_foods.sql      食品30品（暫定値）
├── lib/
│   ├── db.py               接続とパス解決
│   ├── parse.py            入力の構文解析（DB を触らない）
│   ├── resolve.py          種目名・食品名のマスタ解決
│   ├── store.py            DB への書き込みと undo
│   ├── diagnose.py         診断ルールエンジンと制御ループ
│   └── history.py          手書き記録（Markdown）の取り込み
└── tests/test_health.py    テスト（外部ライブラリ不要）
```

## テスト

```bash
python3 skills/health/tests/test_health.py
```

## 既知の制約

- `sqlite3` CLI はこの環境に無い。DB は Python の `sqlite3` モジュール経由で触る
- `foods` の30品は全て `source='estimate'` の暫定値。**初回に買ったとき実物の
  栄養成分表示を見て `'label'` に更新する。** 暫定値のままだと「摂取不足」の判定が信用できない
- 判読不能で未登録の種目2件（`LATERAL LOW` / `シーテッド`）は取り込み時にスキップされる

---
name: health-report
description: 週や月の振り返り。体重の推移から目標カロリーを補正し、停滞している種目と原因を指摘する。ダッシュボード（dashboard.html）を生成する。「最近どう？」「伸びてる？」「なんで停滞してる？」に答える担当
version: 0.1.0
author: ice0622
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Health, Analysis, Review, Dashboard]
    related_skills: [health-log, health-today]
    requires_toolsets: [shell]
    blueprint:
      schedule: "0 21 * * 0"
      deliver: origin
      prompt: |
        `health check` と `health report` を実行し、週次の振り返りを返す。
        体重の週平均がどう動いたか、目標カロリーを変えるべきか、
        停滞している種目とその原因を、合わせて20行以内で。
        表は使わず1行を短く。最後に「来週やること」を1つだけ書く。
        目標カロリーの変更が提案されていれば、適用してよいか聞く（勝手に適用しない）。
---

# Health Report

**伸びているのか、止まっているのか、なぜか**に答える。

## When to Use

- 「最近どう？」「伸びてる？」「先週から変わった？」
- 「なんで停滞してるんだろう」「ベンチが上がらない」
- 日曜21時の定時通知（blueprint）
- ダッシュボードを見たいと言われたとき

使わない: 今日の食事の相談（→ `health-today`）、記録の追加（→ `health-log`）。

## Quick Reference

| 目的 | コマンド |
|---|---|
| 診断（問題点と次のアクション） | `health check` |
| 目標カロリーの補正を適用 | `health check --apply` |
| ダッシュボード生成 | `health report` |

`health check` が見ているもの: 記録の継続 / 体重記録の充足 / 週平均体重の変化 /
摂取カロリーとタンパク質の充足 / トレーニング頻度 / 主要種目の停滞 /
未知食品の滞留 / 暫定値の食品。

## Procedure

1. `health check` を実行する。**これがこのスキルの中核。**
   判定はルールエンジンで、モデルが数字を再解釈する必要はない。

2. 指摘を**優先度順に最大3つ**まで伝える。8個並べると読まれない。
   `[要対応]` は必ず含める。`[OK]` も1つは含める（続いていることが分かるように）。

3. **目標カロリーの変更が提案されていたら、適用するか聞く。**
   勝手に `--apply` しない。いつ・なぜ変えたかを本人が知っている状態を保つ。

4. `health report` を実行して `dashboard.html` を更新する。
   Discord には貼れないので、パスを伝えるだけにする。

5. 停滞の指摘があれば、**原因の候補を摂取・頻度・重量設定の順で挙げる。**
   この順番には理由がある。体重が落ちている期間に筋力は伸びないので、
   種目やフォームより先に摂取と頻度を疑う。

6. 最後に**来週やることを1つだけ**書く。3つ書くと1つも実行されない。

## Pitfalls

- **frontmatter の `blueprint:` は自動でジョブにならない。**
  Hermes は install 時に「提案」として登録するだけで（`cron/suggestions.py`:
  "Suggestions never auto-create jobs; acceptance is always explicit"）、
  さらにローカルのシンボリックリンクは install 経路を通らないので提案も出ない。
  **実際の定時実行は `./scripts/install-cron.sh` が `hermes cron create --no-agent` で作る。**
  frontmatter の blueprint は意図の記録として残している。

- **指摘を全部並べる。** 8個出ると読まれず、1つも直らない。3つまで。
- **`--apply` を勝手に実行する。** 目標が黙って変わると、本人が
  「なぜこの数字なのか」を説明できなくなる。
- **停滞の原因をフォームや種目選択から探す。** 摂取と頻度が先。
  実測では週2.3回の時期に伸び、週1.2〜1.6回の時期に止まっている。
- **数字を再計算する。** `health check` の出力をそのまま使う。
  モデルが平均を取り直すと、ルールエンジンと食い違って混乱する。
- **記録が続いていないときに、内容の分析を続ける。**
  `health check` は記録が0件なら指摘を1つだけ返す設計になっている。
  その場合は入力形式（手段）を疑う話にする。目標の話をしない。
- 「良くなっています」だけで終わる。褒めても行動は変わらない。数字と次の1手を出す。

## Verification

`~/health/dashboard.html` の更新時刻が今であること。
伝えた指摘が3つ以内で、うち1つが `[要対応]` か `[OK]` であること。
来週やることが1つだけ書かれていること。

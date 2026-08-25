---
name: health-today
description: 今日の摂取状況と不足を出し、何をどれだけ買って食べればいいかを具体的な商品名で答える。今日やるトレーニングの種目と目標重量も出す。「あと何食べればいい」「今日何すればいい」に答える担当
version: 0.1.0
author: ice0622
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Health, Nutrition, Fitness, Advice]
    related_skills: [health-log, health-report]
    requires_toolsets: [shell]
    blueprint:
      schedule: "0 18 * * *"
      deliver: origin
      prompt: |
        `health today` と `health check` を実行し、今日の不足を報告する。
        「あと N kcal、タンパク質 M g 足りない」と、それを埋める具体的な商品名を
        3行以内で出す。数値の羅列はせず、買うものだけを短く。表は使わない。
        不足が無ければ「今日は足りている」の1行だけ返す。
---

# Health Today

**今日の残りをどう埋めるか**に答える。増量が目標なので、制限ではなく
「あとどれだけ足すか」を出す。

## When to Use

- 「あと何食べればいい？」「今日何すればいい？」「今どれくらい？」
- 「コンビニで何買えばいい？」「夜何食べる？」
- 18時の定時通知（blueprint）
- 出張・外食など、いつもと違う条件での食事の相談

使わない: 記録の追加（→ `health-log`）、週や月の振り返り（→ `health-report`）。

## Quick Reference

| 目的 | コマンド |
|---|---|
| 今日の摂取と残り | `health today` |
| 問題点と次のアクション | `health check` |
| 目標カロリーの補正を適用 | `health check --apply` |
| 今日やる分割のメニュー | `health t`（引数なしで最も久しぶりの分割） |
| 分割を指定 | `health t push` / `t pull` / `t legs` |

## Procedure

1. `health today` を実行して、残りの kcal / P / F / C を得る。

2. **脂質(F)が既に超過していないか必ず見る。**
   超過していたら、揚げ物・ナッツ・チーズ・卵を勧めない。
   残りは炭水化物と低脂質のタンパク源で埋める。ここを見落とすと助言が逆向きになる。

3. 食品マスタから、残りを埋める組み合わせを作る。
   **モデルが記憶で栄養価を出さない。** マスタの値で計算する。

   ```bash
   health report >/dev/null   # 最新の集計を反映
   ```

   マスタの中身は `sqlite3` ではなく Python で読む（CLI が無い環境のため）:

   ```bash
   python3 -c "
   import sqlite3,pathlib
   c=sqlite3.connect(pathlib.Path.home()/'health/health.db'); c.row_factory=sqlite3.Row
   for r in c.execute('SELECT name,unit,kcal,protein,fat,carb FROM foods ORDER BY protein DESC'):
       print(dict(r))"
   ```

4. **手数が少ない順に最大3案**出す。1案だけだと選べず、4案以上だと決められない。
   各案に合計 kcal とタンパク質を付ける。

5. トレーニングを聞かれたら `health t` を実行し、**前回の重量から今日の目標を出す**。
   - 前回3セット揃わなかった種目 → 重量は上げず、揃えることを目標にする
   - 3セット揃った種目 → 次は重量を上げる
   - 自己最高より下の重量で止まっている種目は、その事実を伝える

6. `health check` の指摘があれば、**最も優先度が高い1つだけ**を添える。
   全部並べると読まれない。

7. 出力は**表を使わず、1行を短く、時間順**にする。スマホで読むため。
   CLIコマンドを出力に混ぜない。

## Pitfalls

- **frontmatter の `blueprint:` は自動でジョブにならない。**
  Hermes は install 時に「提案」として登録するだけで（`cron/suggestions.py`:
  "Suggestions never auto-create jobs; acceptance is always explicit"）、
  さらにローカルのシンボリックリンクは install 経路を通らないので提案も出ない。
  **実際の定時実行は `./scripts/install-cron.sh` が `hermes cron create --no-agent` で作る。**
  frontmatter の blueprint は意図の記録として残している。

- **脂質の超過を見落とす。** 最も起きやすい失敗。カロリーだけ見ると
  「揚げ物を足せ」と言ってしまう。
- **モデルの記憶で栄養価を答える。** 商品改廃でずれるし、マスタとの整合が壊れる。
  必ず DB の値を使う。
- **減量前提の助言をする。** 目標は増量。「控えましょう」は原則として間違い。
  例外は脂質のみ。
- **`source='estimate'` の食品が多いまま「不足している」と断定する。**
  暫定値のままだと不足の判定自体が信用できない。その旨を添える。
- 案を4つ以上出す。決められなくなって行動が変わらない。
- 数値を羅列する。`1431kcal / P121g / F29g` より「これで足りる」の方が行動が変わる。

## Verification

出した案の合計が、`health today` の「残り」に対して ±150kcal 以内であること。
脂質が超過している日に、脂質を足す案を出していないこと。

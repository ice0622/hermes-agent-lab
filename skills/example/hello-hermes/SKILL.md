---
name: hello-hermes
description: このリポジトリのスキルが正しく読み込まれているかを確認する動作検証用スキル。環境情報とスキル自身のパスを報告する
version: 0.1.0
author: ice0622
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Example, Diagnostics, Template]
    requires_toolsets: [shell]
---

# Hello Hermes

このリポジトリ（`hermes-agent-lab`）のスキルが Hermes に認識されているかを確認するための
最小構成のスキル。新しいスキルを作るときのひな形も兼ねる。

## When to Use

次のいずれかに当てはまるとき。

- ユーザーが「スキルが読み込まれているか確認して」と言ったとき
- `hermes-agent-lab` のセットアップ直後で、疎通を確かめたいとき
- 新しいスキルを追加したあと、探索が効いているか見たいとき

日常の会話では読み込まない。動作確認専用。

## Quick Reference

| 目的 | コマンド |
|---|---|
| 診断スクリプトを実行 | `python3 ${HERMES_SKILL_DIR}/scripts/run.py` |
| 認識済みスキル一覧 | `hermes skills list` |
| スキルの探索先 | `${HERMES_HOME:-$HOME/.hermes}/skills` |

## Procedure

1. 診断スクリプトを実行する。

   ```bash
   python3 ${HERMES_SKILL_DIR}/scripts/run.py
   ```

2. 出力される JSON を読む。以下のキーが含まれる。

   - `skill_dir` — このスキルが実際に置かれているパス
   - `is_symlink` — 開発用リンク（`link-dev.sh`）経由かどうか
   - `hermes_home` — Hermes の設定ディレクトリ
   - `python` — 実行中の Python バージョン

3. `is_symlink` が `true` なら開発モード。リポジトリのファイルを編集すれば
   そのまま反映される。`false` なら `hermes skills install` でコピーされた実体を
   見ているので、編集しても元リポジトリには戻らない。

4. 結果をユーザーに1〜2文で報告する。JSON をそのまま貼らず、
   「読み込まれている／いない」「開発モードかどうか」を伝える。

## Pitfalls

- **`${HERMES_SKILL_DIR}` が展開されない場合** — Hermes 経由ではなく直接シェルで叩いている。
  その場合はこのファイルからの相対パスで `scripts/run.py` を指定する。
- **`hermes skills list` に出てこない** — スキルの探索は起動時に走る。追加直後は
  Hermes を再起動する。
- **`SKILL.md` の frontmatter が壊れていると、そのスキルだけ黙って無視される。**
  エラーが出ないので、追加したのに出てこないときは真っ先に YAML を疑う。
- `name` はディレクトリ名と揃える。ずれていると探索結果の表示と実体が食い違う。

## Verification

`hermes skills list` の出力に `hello-hermes` が含まれていること。
かつ診断スクリプトが exit code 0 で JSON を返すこと。

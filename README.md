# hermes-agent-lab

[Nous Research の Hermes Agent](https://github.com/NousResearch/hermes-agent) に生やすカスタムスキル置き場。

Hermes 本体は fork しない。本体は本体のまま更新を受け取り、こちらは**スキルだけを外から足す**。
Hermes は `hermes skills install owner/repo` で GitHub リポジトリから直接スキルを読めるので、
このリポジトリがそのまま配布元（tap）になる。

## 前提

| | |
|---|---|
| Hermes Agent | Python 3.11 + Node.js、パッケージ管理は `uv` |
| 設定ファイル | `~/.hermes/config.yaml` |
| スキル置き場 | `~/.hermes/skills/<category>/<name>/SKILL.md` |
| ライセンス | 本体・本リポジトリともに MIT |

## セットアップ

```bash
./scripts/setup.sh
```

Hermes 本体が未導入なら公式インストーラを叩き、そのあとこのリポジトリのスキルを入れる。
すでに入っている場合は本体をスキップする。

手でやる場合:

```bash
# 1. Hermes 本体
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
source ~/.bashrc

# 2. プロバイダ設定（Nous Portal / OpenRouter / OpenAI / 自前エンドポイント）
hermes setup

# 3. このリポジトリのスキルを入れる
hermes skills install ice0622/hermes-agent-lab
```

## 開発ループ

`hermes skills install` は取得したスキルをコピーするので、**編集するたびに入れ直すことになる**。
それが無駄なので、開発中はシンボリックリンクを張る。

```bash
./scripts/link-dev.sh
```

`skills/` 配下の各スキルを `~/.hermes/skills/` にリンクする。以降はこのリポジトリのファイルを
編集すれば、次に Hermes を起動した時点で反映される。

```bash
./scripts/link-dev.sh --unlink   # 元に戻す
```

反映の確認:

```bash
hermes skills list
```

## スキルを追加する

`skills/<category>/<skill-name>/SKILL.md` を作るだけ。Hermes は起動時に全フォルダを
自動探索するので、登録作業はいらない。

```
skills/
└── example/
    └── hello-hermes/
        ├── SKILL.md          # 必須
        └── scripts/          # 任意。SKILL.md から ${HERMES_SKILL_DIR} で参照する
            └── run.py
```

### SKILL.md のスキーマ

[agentskills.io](https://agentskills.io) 標準に準拠。YAML frontmatter + Markdown 本文。

```yaml
---
name: skill-identifier          # 必須。ディレクトリ名と揃える
description: 検索結果に出る一行説明   # 必須。ここだけ見て呼ぶか決まるので具体的に
version: 1.0.0
author: ice0622
license: MIT
platforms: [linux, macos]       # 省略すると全プラットフォーム
metadata:
  hermes:
    tags: [Category, Keywords]
    related_skills: [other-skill]
    requires_toolsets: [web]      # このスキルが前提にするツール群
    requires_tools: [web_search]
    config:                       # hermes setup で聞かれる設定項目
      - key: mylab.some.setting
        description: "何を制御するか"
        default: "sensible-default"
        prompt: "セットアップ時の表示文"
    blueprint:                    # 定期実行させたい場合のみ
      schedule: "0 9 * * *"
      deliver: origin
      prompt: "各回のタスク指示"
required_environment_variables:
  - name: MY_API_KEY
    prompt: "Enter your API key"
    help: "https://example.com で取得"
    required_for: "API access"
---
```

本文は5節構成にする。エージェントはこれを読んで動くので、**人間向けの説明ではなく
実行手順として**書く。

| 節 | 書くこと |
|---|---|
| `When to Use` | どういう時にこのスキルを読み込むか。トリガー条件 |
| `Quick Reference` | よく使うコマンドやAPIの表 |
| `Procedure` | 手順。番号付きで、迷わない粒度まで落とす |
| `Pitfalls` | 既知の失敗パターンと対処 |
| `Verification` | うまくいったことをどう確認するか |

## ディレクトリ

```
.
├── skills/               ここにスキルを足していく
│   └── example/hello-hermes/
├── scripts/
│   ├── setup.sh          Hermes 導入 + スキル install
│   └── link-dev.sh       開発用シンボリックリンク
└── .env.example          スキルが要求する環境変数のひな形
```

## 参考

- [Hermes Agent 本体](https://github.com/NousResearch/hermes-agent)
- [ドキュメント](https://hermes-agent.nousresearch.com/docs/)
- [スキル作成ガイド](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills)

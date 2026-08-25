# Discord で使う

`docs/spec/io-design.md` の案A（Hermes）の実際の手順と使い方。

---

## 全体像

```
          あなた                                    Hermes
            │
   ┌────────┴─────────┐
   │ #health チャンネル │
   └────────┬─────────┘
            │  ①入力（あなたが打つ）
            ├──────────────► ゲートウェイ ──► エージェント ──► SKILL.md ──► health CLI ──► SQLite
            │                                                                              │
            │  ②返信                                                                       │
            ◄──────────────────────────────────────────────────────────────────────────────┘
            │
            │  ③定時通知（cron --no-agent。LLM を通らない = 無料）
            ◄────────────── cron ──► health-morning.py / evening.py / weekly.py ──► SQLite
```

**チャンネルは1つだけ作る。** 分ける（食事用・筋トレ用…）と、投げる前にどこに投げるか
迷って結局投げなくなる。

---

## セットアップ手順

### 1. Discord Developer Portal での作業

1. [Developer Portal](https://discord.com/developers/applications) → **New Application**
   → 名前をつけて作成。**Application ID** をメモする
2. 左メニュー **Bot** → **Public Bot** を ON（招待リンクを Discord に作らせる場合）
3. **★ 最重要 ★** 同じ Bot ページの **Privileged Gateway Intents** で
   **2つを ON にして Save Changes**
   - **Message Content Intent** ← これが OFF だと**メッセージの中身が空で届き、永久に無反応になる**
   - **Server Members Intent**

   > 公式ドキュメントいわく「Discord bot が動かない理由の1位」。
   > bot はオンラインになるので、設定漏れに気づきにくい。

4. **Token** → **Reset Token** → 表示されたトークンをコピー（**一度しか表示されない**）
5. 左メニュー **Installation** → Guild Install を有効化 →
   Scopes に `bot` と `applications.commands`、Permissions は下記
   （または手で URL を組む）

   ```
   https://discord.com/oauth2/authorize?client_id=<APP_ID>&scope=bot+applications.commands&permissions=274878286912
   ```

   必要な権限: View Channels / Send Messages / Embed Links / Attach Files /
   Read Message History（`274878286912` に含まれる）

6. その URL を開いて、自分のサーバーに招待する

### 2. ID を2つ取る

Discord の **設定 → 詳細設定 → 開発者モード** を ON にすると、右クリックで ID がコピーできる。

- **自分の User ID** — 自分の名前を右クリック → ID をコピー
- **チャンネル ID** — 使うチャンネル（`#health` など）を右クリック → ID をコピー

### 3. Hermes 側の設定

```bash
./scripts/setup-discord.sh <BOT_TOKEN> <あなたのUSER_ID> <CHANNEL_ID>
```

これで `~/.hermes/.env` に次が書かれる（パーミッションは 600）。

| 設定 | 値 | 理由 |
|---|---|---|
| `DISCORD_BOT_TOKEN` | トークン | 必須 |
| `DISCORD_ALLOWED_USERS` | あなたの ID | これが無いと全員拒否される |
| `DISCORD_HOME_CHANNEL` | チャンネル ID | **定時通知の配信先** |
| `DISCORD_FREE_RESPONSE_CHANNELS` | チャンネル ID | **@メンション不要にする。** 毎回タグ付けが要ると記録をやめる |
| `DISCORD_ALLOWED_CHANNELS` | チャンネル ID | このチャンネル以外では反応しない |
| `DISCORD_AUTO_THREAD` | `false` | **既定は true で、1メッセージごとにスレッドが立って履歴が断片化する** |
| `DISCORD_REACTIONS` | `true` | 👀→✅ で処理中/完了が分かる |

同時に定時通知の配信先が `local` → `discord` に切り替わる。

### 4. API キー

```bash
hermes config set --env ANTHROPIC_API_KEY sk-ant-...
```

**先に [Console で spend limit](https://console.anthropic.com/settings/limits) を設定する。**

### 5. 起動

```bash
hermes gateway run     # WSL は foreground 推奨（公式の表示どおり）
```

bot がオンラインになったら疎通確認。チャンネルに `w 64.2` と送る。

---

## 使い方

### 記録する（打つ）

**定型で打つと LLM を通らないので無料。** スキルに「先頭が既知のコマンド形式なら
解釈せずそのまま実行する」と書いてある。

```
w 64.2                          体重
sq 30 8,8,8                     スクワット 30kg を 8回×3セット
dl 42 8,8,8
m 鯖の味噌煮, ご飯（炊いたもの）*2, 豚汁
t                               今日やる分割のメニュー
undo                            直前を取り消す
```

**雑に書いてもいい**（こちらは Haiku を1回呼ぶ）。

```
昼は鯖の味噌煮とご飯2杯と豚汁
スクワット30キロ8回3セットやった
```

**食事を記録すると、残りが自動で返る。** 「どれくらい足りない？」と聞き直す必要はない。

```
あなた: m 鯖の味噌煮, ご飯（炊いたもの）*2
Hermes: 記録: 鯖の味噌煮×1  ご飯（炊いたもの）×2  →  718kcal / P 25g
        あと 1380kcal / タンパク質 51g
```

### 聞く

```
あと何食べればいい？
今日何すればいい？
最近伸びてる？
なんでベンチ止まってるんだろう
明日出張だけど何買っておけばいい？
```

最後のような定型化できない質問がエージェントの本番。ここだけコストがかかる。

### 届くもの（自動・無料）

| 時刻 | 内容 |
|---|---|
| **07:00** | 今日のメニュー。体重測定の催促 / 目標 / 今日の分割と種目・目標重量 |
| **18:00** | 不足通知。「あと N kcal / タンパク質 M g」＋献立の候補3案 |
| **日曜21:00** | 週次ふりかえり。指摘3つまで＋目標カロリーの変更提案 |

**この3本は `--no-agent` なので LLM を通らない = トークン0円。**

通知を3本より増やさないこと。無視する習慣がつくと、チャンネル全体が信用を失って
必要な通知も見なくなる。

---

## コスト

| | LLM | 目安 |
|---|---|---|
| 定時通知（3本） | 通らない | **$0** |
| 定型入力（`w 64.2`） | 通らない | **$0** |
| 雑な記録（自由文） | Haiku 1回 | 約$0.0045/件 |
| 質問 | エージェント1ターン | 約$0.017〜$0.10/件 |

$41 のクレジットなら、1日10メッセージ（うち自由文3・質問1）で **4ヶ月〜1年**。

---

## 詰まったときは

| 症状 | 原因 |
|---|---|
| **bot はオンラインだが無反応** | **Message Content Intent が OFF。** これが原因の1位 |
| 「権限がない」と拒否される | `DISCORD_ALLOWED_USERS` に自分の User ID が入っていない |
| @メンションしないと反応しない | `DISCORD_FREE_RESPONSE_CHANNELS` にチャンネル ID が入っていない |
| メッセージごとにスレッドが立つ | `DISCORD_AUTO_THREAD=false` になっていない |
| 定時通知が来ない | **ゲートウェイが動いていない。** `hermes cron status` で確認 |
| PC を閉じたら止まった | WSL は常時稼働ではない。VPS へ移す（`docs/spec/io-design.md`） |

---

## 常時稼働について

**WSL2 では PC を閉じると送信も受信も止まる。** 朝7時の通知を確実に受けるには
常時稼働のホストが要る。

- 推論は Claude API に投げるので **GPU は無関係**。1GB の最小構成で足りる
- 月700円程度の VPS
- 移設後は `hermes gateway install`（systemd）で常駐させる

それまでは、PC を開けている間だけ `hermes gateway run` で動く。
まず1週間その形で使って、本当に18時の通知が要るかを確かめてから借りるのが安全。

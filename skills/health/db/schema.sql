-- 健康管理エージェント スキーマ
-- 仕様: docs/spec/health-agent.md
--
--   sqlite3 ~/health/health.db < skills/health/db/schema.sql
--
-- 設計上の要点:
--  * meals は栄養価を「記録時点の値」でスナップショットする。foods を後から訂正しても
--    過去の集計が黙って書き換わらないようにするため。
--  * body.body_fat は NULL 可、source 列を最初から持つ。タニタ Health Planet 連携を
--    後から足してもスキーマ変更が発生しないようにするため。
--  * routines は曜日ではなく split（Push/Pull/Legs）で持つ。実測1年分（docs/training-history.md）
--    で曜日が固定されていないことが確認されたため。

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================ 食事

CREATE TABLE IF NOT EXISTS foods (
  id       INTEGER PRIMARY KEY,
  name     TEXT    NOT NULL UNIQUE,   -- 'サラダチキン'
  alias    TEXT,                      -- 'サラチキ,チキン' 入力揺れの吸収（カンマ区切り）
  unit     TEXT    NOT NULL,          -- '個' 'g' '杯' '本' '枚'
  unit_g   REAL,                      -- 1単位のグラム数（任意）
  kcal     REAL    NOT NULL,          -- 以下すべて 1単位あたり
  protein  REAL    NOT NULL,
  fat      REAL    NOT NULL,
  carb     REAL    NOT NULL,
  source   TEXT    NOT NULL DEFAULT 'estimate',  -- 'estimate' | 'label' | 'mext' | 'llm'
  created_at TEXT  NOT NULL DEFAULT (datetime('now','localtime'))
);

-- source='estimate' は暫定値。初回購入時に実物のラベルを見て 'label' に更新する。

CREATE TABLE IF NOT EXISTS meals (
  id        INTEGER PRIMARY KEY,
  eaten_at  TEXT NOT NULL,             -- '2026-08-24 12:30'
  date      TEXT NOT NULL,             -- '2026-08-24' 集計用に冗長保持
  food_id   INTEGER REFERENCES foods(id),
  food_name TEXT NOT NULL,             -- 当時の名前を残す
  qty       REAL NOT NULL DEFAULT 1,
  kcal      REAL NOT NULL,             -- ↓ 記録時点のスナップショット
  protein   REAL NOT NULL,
  fat       REAL NOT NULL,
  carb      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meals_date ON meals(date);

-- ============================================================ トレーニング

CREATE TABLE IF NOT EXISTS exercises (
  id     INTEGER PRIMARY KEY,
  code   TEXT NOT NULL UNIQUE,         -- 'bp'
  name   TEXT NOT NULL,                -- 'ベンチプレス'
  muscle TEXT NOT NULL,                -- '胸'
  split  TEXT NOT NULL                 -- 'push' | 'pull' | 'legs'
);

CREATE TABLE IF NOT EXISTS routines (
  id          INTEGER PRIMARY KEY,
  split       TEXT    NOT NULL,        -- 'push' | 'pull' | 'legs'
  exercise_id INTEGER NOT NULL REFERENCES exercises(id),
  ord         INTEGER NOT NULL,        -- 表示順 = `t push` で出る番号
  UNIQUE(split, ord)
);

CREATE TABLE IF NOT EXISTS sets (
  id          INTEGER PRIMARY KEY,
  trained_at  TEXT    NOT NULL,
  date        TEXT    NOT NULL,
  exercise_id INTEGER NOT NULL REFERENCES exercises(id),
  weight      REAL    NOT NULL,        -- kg
  reps        INTEGER NOT NULL,
  set_no      INTEGER NOT NULL,
  note        TEXT
);
CREATE INDEX IF NOT EXISTS idx_sets_date ON sets(date);
CREATE INDEX IF NOT EXISTS idx_sets_ex   ON sets(exercise_id, date);

-- ============================================================ 体組成

CREATE TABLE IF NOT EXISTS body (
  id          INTEGER PRIMARY KEY,
  measured_at TEXT NOT NULL,
  date        TEXT NOT NULL UNIQUE,    -- 1日1件
  weight      REAL NOT NULL,
  body_fat    REAL,                    -- タニタ導入後に埋まる
  muscle      REAL,
  source      TEXT NOT NULL DEFAULT 'manual'   -- 'manual' | 'tanita'
);

-- ============================================================ 目標（制御ループが書き換える）

CREATE TABLE IF NOT EXISTS targets (
  id             INTEGER PRIMARY KEY,
  effective_from TEXT NOT NULL,
  kcal    REAL NOT NULL,
  protein REAL NOT NULL,
  fat     REAL NOT NULL,
  carb    REAL NOT NULL,
  note    TEXT                          -- '週平均+50gしか増えないので +200kcal'
);

-- ============================================================ ビュー

-- 今日の摂取合計
CREATE VIEW IF NOT EXISTS v_today AS
SELECT
  date,
  ROUND(SUM(kcal))    AS kcal,
  ROUND(SUM(protein)) AS protein,
  ROUND(SUM(fat))     AS fat,
  ROUND(SUM(carb))    AS carb
FROM meals
WHERE date = date('now','localtime')
GROUP BY date;

-- 現在有効な目標
CREATE VIEW IF NOT EXISTS v_target AS
SELECT * FROM targets
WHERE effective_from <= date('now','localtime')
ORDER BY effective_from DESC, id DESC
LIMIT 1;

-- 体重の週平均（制御ループの入力）
CREATE VIEW IF NOT EXISTS v_weight_weekly AS
SELECT
  strftime('%Y-W%W', date) AS week,
  ROUND(AVG(weight), 2)    AS avg_weight,
  COUNT(*)                 AS n
FROM body
GROUP BY week
ORDER BY week DESC;

-- 種目ごとの推定1RM推移（Epley）
CREATE VIEW IF NOT EXISTS v_1rm AS
SELECT
  e.code, e.name, s.date,
  MAX(ROUND(s.weight * (1 + s.reps / 30.0), 1)) AS est_1rm
FROM sets s JOIN exercises e ON e.id = s.exercise_id
GROUP BY e.code, s.date
ORDER BY s.date DESC;

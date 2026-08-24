-- 種目マスタ / ルーティン
-- 出典: docs/training-history.md（2025-09-20 〜 2026-08-19、86セッションの実測）
-- 「やるべき種目」ではなく「実際にやっている種目」だけを登録している。

-- ============================================================ exercises

INSERT OR IGNORE INTO exercises (code, name, muscle, split) VALUES
-- Push
('bp',  'ベンチプレス',                   '胸',       'push'),
('dbp', 'ダンベルプレス',                 '胸',       'push'),
('idp', 'インクラインダンベルプレス',     '胸',       'push'),
('isp', 'インクラインシーテッドプレス',   '胸',       'push'),
('smb', 'スミスベンチ',                   '胸',       'push'),
('pf',  'ペックフライ',                   '胸',       'push'),
('sp',  'ショルダープレス（ダンベル）',   '肩',       'push'),
('msp', 'ショルダープレス（マシン）',     '肩',       'push'),
('sr',  'サイドレイズ',                   '肩',       'push'),
('csr', 'ケーブルサイドレイズ',           '肩',       'push'),
('cpd', 'ケーブルプレスダウン',           '三頭',     'push'),
('cad', 'ケーブルアームダウン',           '三頭',     'push'),

-- Pull
('lpd', 'ラットプルダウン',               '背中',     'pull'),
('wpd', 'ワイドプルダウン',               '背中',     'pull'),
('cpl', 'ケーブルプルダウン',             '背中',     'pull'),
('row', 'ローイング（シーテッド）',       '背中',     'pull'),
('prow','パラレルローイング',             '背中',     'pull'),
('iso', 'アイソラテラルロー',             '背中',     'pull'),
('dbr', 'ダンベルロー',                   '背中',     'pull'),
('bbr', 'バーベルロー',                   '背中',     'pull'),
('ogr', 'オーバーグリップロー',           '背中',     'pull'),
('shr', 'ロー（ショルダー13）',           '背中',     'pull'),
('pu',  '懸垂',                           '背中',     'pull'),
('fp',  'フェイスプル',                   '肩後部',   'pull'),
('dbc', 'ダンベルカール',                 '二頭',     'pull'),
('idc', 'インクラインダンベルカール',     '二頭',     'pull'),
('hc',  'ハンマーカール',                 '二頭',     'pull'),
('bbc', 'バーベルカール',                 '二頭',     'pull'),
('ezc', 'EZバーカール',                   '二頭',     'pull'),
('cc',  'ケーブルカール',                 '二頭',     'pull'),

-- Legs
('sq',  'スクワット',                     '脚',       'legs'),
('dl',  'デッドリフト',                   '脚/背中',  'legs'),
('lpr', 'レッグプレス',                   '脚',       'legs'),
('slp', 'シーテッドレッグプレス',         '脚',       'legs'),
('le',  'レッグエクステンション',         '大腿四頭', 'legs'),
('lc',  'レッグカール',                   'ハム',     'legs'),
('slc', 'シーテッドレッグカール',         'ハム',     'legs'),
('cr',  'シーテッドカーフレイズ',         'ふくらはぎ','legs'),
('ha',  'ヒップアブダクター',             '臀部',     'legs');

-- 判読不明で未登録: 'LATERAL LOW'（4/11, 4/18）、'シーテッド'（3/20）
-- 次回ジムで確認してから追加する。

-- ============================================================ routines
-- `t push` で番号付きで出る順。実測で最も頻出する組み合わせを上位に置いた。

INSERT OR IGNORE INTO routines (split, exercise_id, ord)
SELECT 'push', id, ord FROM (
  SELECT (SELECT id FROM exercises WHERE code='bp')  AS id, 1 AS ord
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='sp'),  2
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='sr'),  3
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='msp'), 4
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='idp'), 5
);

INSERT OR IGNORE INTO routines (split, exercise_id, ord)
SELECT 'pull', id, ord FROM (
  SELECT (SELECT id FROM exercises WHERE code='lpd') AS id, 1 AS ord
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='row'), 2
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='dbc'), 3
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='dbr'), 4
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='pu'),  5
);

INSERT OR IGNORE INTO routines (split, exercise_id, ord)
SELECT 'legs', id, ord FROM (
  SELECT (SELECT id FROM exercises WHERE code='sq')  AS id, 1 AS ord
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='dl'),  2
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='lpr'), 3
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='le'),  4
  UNION ALL SELECT (SELECT id FROM exercises WHERE code='lc'),  5
);

-- ============================================================ 初期の目標値
-- 178cm / 64kg / 25歳 / 活動係数1.55 → TDEE 2,530kcal、リーンバルクで +300kcal

INSERT OR IGNORE INTO targets (effective_from, kcal, protein, fat, carb, note) VALUES
('2026-08-24', 2830, 130, 60, 440,
 '初期値。Mifflin-St Jeor + 1.55 で TDEE 2530kcal、リーンバルクで +300kcal。実測で毎週補正する。');

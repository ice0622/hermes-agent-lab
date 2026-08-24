"""健康管理エージェントの共通ライブラリ。

  db.py        接続とパス解決
  parse.py     入力の構文解析（DB を触らない）
  resolve.py   種目名・食品名のマスタ解決
  diagnose.py  診断ルールエンジンと制御ループ
  history.py   手書き記録（Markdown）の取り込み
"""

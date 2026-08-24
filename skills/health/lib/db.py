"""DB 接続とパス解決。

DB の場所は環境変数 HEALTH_DB、無ければ ~/health/health.db。
sqlite3 CLI はこの環境に入っていないので、必ず Python の sqlite3 経由で触る。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # skills/health/
DDL_DIR = REPO_ROOT / "db"


def db_path() -> Path:
    env = os.environ.get("HEALTH_DB")
    return Path(env) if env else Path.home() / "health" / "health.db"


def connect(path: Path | None = None, *, create: bool = False) -> sqlite3.Connection:
    p = path or db_path()
    if not create and not p.exists():
        raise SystemExit(
            f"DB がありません: {p}\n先に `health init` を実行してください。"
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def current_target(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM v_target").fetchone()

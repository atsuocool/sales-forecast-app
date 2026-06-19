import os
import sqlite3
from pathlib import Path


def is_db_initialized(db_path: str) -> bool:
    """DBファイルが存在し、かつ market_data テーブルが作成済みかを確認する。
    ファイルだけ存在して空の場合に False を返す点が重要。
    """
    if not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_data'"
        ).fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


def get_connection(db_path: str = "data/pharma_forecast.db") -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

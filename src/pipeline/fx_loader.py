import sqlite3
import pandas as pd

DATA_DIR = "docs/sample_data"


def load_fx_rates(
    conn: sqlite3.Connection,
    csv_path: str = f"{DATA_DIR}/fx_rates_sample.csv",
) -> int:
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    df["jpy_per_usd"] = pd.to_numeric(df["jpy_per_usd"], errors="coerce")

    conn.executemany(
        "INSERT OR IGNORE INTO fx_rates "
        "(rate_type, period, jpy_per_usd, updated_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        df[["rate_type", "period", "jpy_per_usd", "updated_by", "updated_at"]].values.tolist(),
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0]

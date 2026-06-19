import sqlite3
import pandas as pd
from pathlib import Path

# ingredient_name（CSV）→ ingredient_id（マスタ）の名前引きマップ
def _build_name_to_id(conn: sqlite3.Connection) -> dict[str, str]:
    cur = conn.execute("SELECT ingredient_id, name FROM ingredients")
    return {row[1]: row[0] for row in cur.fetchall()}


def load_iqvia(conn: sqlite3.Connection, csv_path: str = "docs/sample_data/iqvia_market_data.csv") -> int:
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    name_to_id = _build_name_to_id(conn)

    df["ingredient_id"] = df["ingredient_name"].map(name_to_id)
    missing = df[df["ingredient_id"].isna()]["ingredient_name"].unique()
    if len(missing):
        raise ValueError(f"ingredient_name がマスタに存在しません: {missing.tolist()}")

    df["sales_units"]    = pd.to_numeric(df["sales_units"],    errors="coerce")
    df["unit_price_jpy"] = pd.to_numeric(df["unit_price_jpy"], errors="coerce")
    df["sales_amount_jpy"] = pd.to_numeric(df["sales_amount_jpy"], errors="coerce")
    df["generic_biosimilar_penetration_rate"] = pd.to_numeric(
        df["generic_biosimilar_penetration_rate"], errors="coerce"
    )

    cols = ["period", "ingredient_id", "manufacturer_type", "product_name",
            "formulation", "sales_units", "unit_price_jpy", "sales_amount_jpy",
            "generic_biosimilar_penetration_rate"]
    rows = df[cols].values.tolist()

    conn.executemany(
        """INSERT OR IGNORE INTO market_data
           (period, ingredient_id, manufacturer_type, product_name, formulation,
            sales_units, unit_price_jpy, sales_amount_jpy, generic_biosimilar_penetration_rate)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]

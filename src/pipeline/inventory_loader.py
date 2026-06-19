import sqlite3
import pandas as pd

DATA_DIR = "docs/sample_data"


def load_sellin(conn: sqlite3.Connection, csv_path: str = f"{DATA_DIR}/sellin_data.csv") -> int:
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    df["quantity"]   = pd.to_numeric(df["quantity"],   errors="coerce")
    df["amount_jpy"] = pd.to_numeric(df["amount_jpy"], errors="coerce")

    conn.executemany(
        "INSERT OR IGNORE INTO sellin_data (period, sku_id, distributor, quantity, amount_jpy) VALUES (?, ?, ?, ?, ?)",
        df[["period", "sku_id", "distributor", "quantity", "amount_jpy"]].values.tolist(),
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM sellin_data").fetchone()[0]


def load_sellout(conn: sqlite3.Connection, csv_path: str = f"{DATA_DIR}/sellout_data.csv") -> int:
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    df["quantity"]   = pd.to_numeric(df["quantity"],   errors="coerce")
    df["amount_jpy"] = pd.to_numeric(df["amount_jpy"], errors="coerce")

    conn.executemany(
        "INSERT OR IGNORE INTO sellout_data (period, sku_id, facility_type, quantity, amount_jpy) VALUES (?, ?, ?, ?, ?)",
        df[["period", "sku_id", "facility_type", "quantity", "amount_jpy"]].values.tolist(),
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM sellout_data").fetchone()[0]


def load_inventory(conn: sqlite3.Connection, csv_path: str = f"{DATA_DIR}/inventory_data.csv") -> int:
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    df["ending_inventory_qty"]        = pd.to_numeric(df["ending_inventory_qty"],        errors="coerce")
    df["ending_inventory_amount_jpy"] = pd.to_numeric(df["ending_inventory_amount_jpy"], errors="coerce")

    conn.executemany(
        "INSERT OR IGNORE INTO inventory_data "
        "(period, sku_id, distributor, ending_inventory_qty, ending_inventory_amount_jpy) "
        "VALUES (?, ?, ?, ?, ?)",
        df[["period", "sku_id", "distributor", "ending_inventory_qty", "ending_inventory_amount_jpy"]].values.tolist(),
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM inventory_data").fetchone()[0]


def load_regulatory_events(conn: sqlite3.Connection, csv_path: str = f"{DATA_DIR}/regulatory_events_sample.csv") -> int:
    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")

    # 旧フォーマット（impact_value_price_change_rate 列）との互換処理
    if "impact_value_price_change_rate" in df.columns and "impact_value" not in df.columns:
        df = df.rename(columns={"impact_value_price_change_rate": "impact_value"})
        df["impact_target"]     = "price"
        df["impact_parameter"]  = "price_change_rate"
        df["effect_lag_months"] = 0

    df["impact_value"]      = pd.to_numeric(df["impact_value"],      errors="coerce")
    df["effect_lag_months"] = pd.to_numeric(df["effect_lag_months"], errors="coerce").fillna(0).astype(int)

    conn.executemany(
        "INSERT OR IGNORE INTO regulatory_events "
        "(event_date, event_type, impact_scope, impact_target, impact_parameter, impact_value, effect_lag_months, memo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        df[["event_date", "event_type", "impact_scope", "impact_target",
            "impact_parameter", "impact_value", "effect_lag_months", "memo"]].values.tolist(),
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM regulatory_events").fetchone()[0]

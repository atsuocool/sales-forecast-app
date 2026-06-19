import sqlite3
import pandas as pd
from pathlib import Path

SAMPLE_DIR = Path("docs/sample_data")


def load_masters(conn: sqlite3.Connection, data_dir="docs/sample_data") -> dict[str, int]:
    d = Path(data_dir)

    df_ta = pd.read_csv(d / "master_therapeutic_areas.csv", dtype=str, encoding="utf-8-sig")
    conn.executemany(
        "INSERT OR IGNORE INTO therapeutic_areas (therapeutic_area_id, name) VALUES (?, ?)",
        df_ta[["therapeutic_area_id", "name"]].values.tolist(),
    )

    df_ing = pd.read_csv(d / "master_ingredients.csv", dtype=str, encoding="utf-8-sig")
    conn.executemany(
        "INSERT OR IGNORE INTO ingredients (ingredient_id, therapeutic_area_id, name, drug_type) VALUES (?, ?, ?, ?)",
        df_ing[["ingredient_id", "therapeutic_area_id", "name", "drug_type"]].values.tolist(),
    )

    df_prod = pd.read_csv(d / "master_products.csv", dtype=str, encoding="utf-8-sig")
    conn.executemany(
        "INSERT OR IGNORE INTO products (product_id, ingredient_id, product_name, type) VALUES (?, ?, ?, ?)",
        df_prod[["product_id", "ingredient_id", "product_name", "type"]].values.tolist(),
    )

    df_sku = pd.read_csv(d / "master_skus.csv", dtype=str, encoding="utf-8-sig")
    df_sku = df_sku.where(pd.notna(df_sku), None)
    conn.executemany(
        "INSERT OR IGNORE INTO skus (sku_id, product_id, package_form, package_size, strength, unit, jan_code, launch_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        df_sku[["sku_id", "product_id", "package_form", "package_size", "strength", "unit", "jan_code", "launch_date"]].values.tolist(),
    )

    conn.commit()

    return {
        "therapeutic_areas": conn.execute("SELECT COUNT(*) FROM therapeutic_areas").fetchone()[0],
        "ingredients":        conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0],
        "products":           conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "skus":               conn.execute("SELECT COUNT(*) FROM skus").fetchone()[0],
    }

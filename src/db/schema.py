import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS therapeutic_areas (
    therapeutic_area_id TEXT PRIMARY KEY,
    name                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id        TEXT PRIMARY KEY,
    therapeutic_area_id  TEXT NOT NULL REFERENCES therapeutic_areas(therapeutic_area_id),
    name                 TEXT NOT NULL,
    drug_type            TEXT NOT NULL CHECK(drug_type IN ('generic', 'biosimilar'))
);

CREATE TABLE IF NOT EXISTS products (
    product_id    TEXT PRIMARY KEY,
    ingredient_id TEXT NOT NULL REFERENCES ingredients(ingredient_id),
    product_name  TEXT NOT NULL,
    type          TEXT NOT NULL CHECK(type IN ('generic', 'biosimilar'))
);

CREATE TABLE IF NOT EXISTS skus (
    sku_id        TEXT PRIMARY KEY,
    product_id    TEXT NOT NULL REFERENCES products(product_id),
    package_form  TEXT NOT NULL,
    package_size  TEXT NOT NULL,
    strength      TEXT NOT NULL,
    unit          TEXT,
    jan_code      TEXT,
    launch_date   TEXT
);

CREATE TABLE IF NOT EXISTS market_data (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    period                       TEXT NOT NULL,
    ingredient_id                TEXT NOT NULL REFERENCES ingredients(ingredient_id),
    manufacturer_type            TEXT NOT NULL,
    product_name                 TEXT,
    formulation                  TEXT,
    sales_units                  REAL,
    unit_price_jpy               REAL,
    sales_amount_jpy             REAL,
    generic_biosimilar_penetration_rate REAL,
    UNIQUE(period, ingredient_id, manufacturer_type, product_name)
);

CREATE TABLE IF NOT EXISTS sellin_data (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    period      TEXT NOT NULL,
    sku_id      TEXT NOT NULL REFERENCES skus(sku_id),
    distributor TEXT NOT NULL,
    quantity    REAL NOT NULL,
    amount_jpy  REAL NOT NULL,
    UNIQUE(period, sku_id, distributor)
);

CREATE TABLE IF NOT EXISTS sellout_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    period        TEXT NOT NULL,
    sku_id        TEXT NOT NULL REFERENCES skus(sku_id),
    facility_type TEXT NOT NULL,
    quantity      REAL NOT NULL,
    amount_jpy    REAL NOT NULL,
    UNIQUE(period, sku_id, facility_type)
);

CREATE TABLE IF NOT EXISTS inventory_data (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    period                       TEXT NOT NULL,
    sku_id                       TEXT NOT NULL REFERENCES skus(sku_id),
    distributor                  TEXT NOT NULL,
    ending_inventory_qty         REAL NOT NULL,
    ending_inventory_amount_jpy  REAL,
    UNIQUE(period, sku_id, distributor)
);

CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date        TEXT NOT NULL,
    event_type        TEXT NOT NULL,
    impact_scope      TEXT NOT NULL,
    impact_target     TEXT NOT NULL DEFAULT 'price',
    impact_parameter  TEXT,
    impact_value      REAL,
    effect_lag_months INTEGER NOT NULL DEFAULT 0,
    memo              TEXT
);

CREATE TABLE IF NOT EXISTS fx_rates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_type   TEXT NOT NULL CHECK(rate_type IN ('historical', 'forecast_assumption')),
    period      TEXT NOT NULL,
    jpy_per_usd REAL NOT NULL,
    updated_by  TEXT,
    updated_at  TEXT,
    UNIQUE(rate_type, period)
);

CREATE TABLE IF NOT EXISTS forecast_log (
    log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    ing_id       TEXT,
    axis1        TEXT,
    axis2        TEXT,
    currency     TEXT,
    fc_y1_jpy    REAL,
    fc_y2_jpy    REAL,
    fc_y3_jpy    REAL,
    triggered_by TEXT
);
"""


def _migrate_regulatory_events(conn: sqlite3.Connection) -> None:
    """既存 DB の regulatory_events テーブルに新列を追加する（冪等）。"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(regulatory_events)")}
    migrations = [
        ("impact_target",     "TEXT NOT NULL DEFAULT 'price'"),
        ("impact_parameter",  "TEXT"),
        ("impact_value",      "REAL"),
        ("effect_lag_months", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, definition in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE regulatory_events ADD COLUMN {col} {definition}")
    conn.commit()


def create_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    _migrate_regulatory_events(conn)
    conn.commit()


def log_forecast(
    conn: sqlite3.Connection,
    ing_id: str,
    axis1: str,
    axis2: str,
    currency: str,
    fc_y1: float,
    fc_y2: float,
    fc_y3: float,
    triggered_by: str = "manual",
) -> None:
    conn.execute(
        "INSERT INTO forecast_log (ing_id, axis1, axis2, currency, fc_y1_jpy, fc_y2_jpy, fc_y3_jpy, triggered_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ing_id, axis1, axis2, currency, fc_y1, fc_y2, fc_y3, triggered_by),
    )
    conn.commit()

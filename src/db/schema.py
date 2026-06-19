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
    event_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date                TEXT NOT NULL,
    event_type                TEXT NOT NULL,
    impact_scope              TEXT NOT NULL,
    impact_value_price_change_rate REAL,
    memo                      TEXT
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
"""


def create_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()

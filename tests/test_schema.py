import sqlite3
import pytest
from src.db.schema import create_all_tables

EXPECTED_TABLES = [
    "therapeutic_areas", "ingredients", "products", "skus",
    "market_data", "sellin_data", "sellout_data", "inventory_data",
    "regulatory_events", "fx_rates",
]


def test_create_all_tables(mem_conn):
    create_all_tables(mem_conn)
    cur = mem_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    for t in EXPECTED_TABLES:
        assert t in tables, f"Table '{t}' not created"


def test_foreign_key_enforced(mem_conn):
    create_all_tables(mem_conn)
    with pytest.raises(sqlite3.IntegrityError):
        mem_conn.execute(
            "INSERT INTO ingredients (ingredient_id, therapeutic_area_id, name, drug_type) "
            "VALUES ('ING99', 'TA_NONEXISTENT', 'Test', 'generic')"
        )
        mem_conn.commit()

import pytest
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia

DATA_DIR = "docs/sample_data"
IQVIA_CSV = "docs/sample_data/iqvia_market_data.csv"


@pytest.fixture
def master_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    return mem_conn


def test_load_iqvia_row_count(master_conn):
    count = load_iqvia(master_conn, IQVIA_CSV)
    assert count == 656


def test_row_has_required_fields(master_conn):
    load_iqvia(master_conn, IQVIA_CSV)
    cur = master_conn.execute(
        "SELECT ingredient_id, sales_units, sales_amount_jpy, generic_biosimilar_penetration_rate "
        "FROM market_data WHERE ingredient_id = 'ING01' AND period = '2023-01' AND manufacturer_type = '自社'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row["sales_units"] > 0
    assert row["sales_amount_jpy"] > 0


def test_all_ingredients_present(master_conn):
    load_iqvia(master_conn, IQVIA_CSV)
    cur = master_conn.execute("SELECT COUNT(DISTINCT ingredient_id) FROM market_data")
    assert cur.fetchone()[0] == 4


def test_idempotent(master_conn):
    load_iqvia(master_conn, IQVIA_CSV)
    load_iqvia(master_conn, IQVIA_CSV)
    cur = master_conn.execute("SELECT COUNT(*) FROM market_data")
    assert cur.fetchone()[0] == 656

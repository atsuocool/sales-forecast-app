from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
import pytest

DATA_DIR = "docs/sample_data"


@pytest.fixture
def loaded_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    return mem_conn


def test_counts(loaded_conn):
    counts = load_masters(loaded_conn, DATA_DIR)  # idempotent
    assert counts["therapeutic_areas"] == 4
    assert counts["ingredients"] == 4
    assert counts["products"] == 4
    assert counts["skus"] == 7


def test_hierarchy_links(loaded_conn):
    cur = loaded_conn.execute(
        "SELECT ta.name FROM therapeutic_areas ta "
        "JOIN ingredients i ON i.therapeutic_area_id = ta.therapeutic_area_id "
        "WHERE i.ingredient_id = 'ING01'"
    )
    assert cur.fetchone()[0] == "代謝・内分泌領域"


def test_product_type(loaded_conn):
    cur = loaded_conn.execute("SELECT type FROM products WHERE product_id = 'PROD03'")
    assert cur.fetchone()[0] == "biosimilar"


def test_sku_links_product(loaded_conn):
    cur = loaded_conn.execute("SELECT COUNT(*) FROM skus WHERE product_id = 'PROD01'")
    assert cur.fetchone()[0] == 2


def test_idempotent(loaded_conn):
    load_masters(loaded_conn, DATA_DIR)
    cur = loaded_conn.execute("SELECT COUNT(*) FROM skus")
    assert cur.fetchone()[0] == 7

import pytest
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.inventory_loader import load_sellin, load_sellout, load_inventory, load_regulatory_events

DATA_DIR = "docs/sample_data"


@pytest.fixture
def master_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    return mem_conn


def test_load_sellin(master_conn):
    n = load_sellin(master_conn, f"{DATA_DIR}/sellin_data.csv")
    assert n == 861


def test_load_sellout(master_conn):
    n = load_sellout(master_conn, f"{DATA_DIR}/sellout_data.csv")
    assert n == 738


def test_load_inventory(master_conn):
    n = load_inventory(master_conn, f"{DATA_DIR}/inventory_data.csv")
    assert n == 861


def test_sellin_has_distributors(master_conn):
    load_sellin(master_conn, f"{DATA_DIR}/sellin_data.csv")
    cur = master_conn.execute("SELECT DISTINCT distributor FROM sellin_data")
    distributors = {row[0] for row in cur.fetchall()}
    assert distributors == {"卸A", "卸B", "卸C"}


def test_inventory_non_negative(master_conn):
    load_inventory(master_conn, f"{DATA_DIR}/inventory_data.csv")
    cur = master_conn.execute("SELECT MIN(ending_inventory_qty) FROM inventory_data")
    assert cur.fetchone()[0] >= 0


def test_sellin_and_sellout_both_positive(master_conn):
    # 在庫取り崩し月ではSell-out > Sell-inになり得るため合計値の大小は問わない
    load_sellin(master_conn,  f"{DATA_DIR}/sellin_data.csv")
    load_sellout(master_conn, f"{DATA_DIR}/sellout_data.csv")
    si = master_conn.execute("SELECT SUM(quantity) FROM sellin_data").fetchone()[0]
    so = master_conn.execute("SELECT SUM(quantity) FROM sellout_data").fetchone()[0]
    assert si > 0
    assert so > 0


def test_load_regulatory_events(master_conn):
    n = load_regulatory_events(master_conn, f"{DATA_DIR}/regulatory_events_sample.csv")
    assert n == 5  # 薬価改定3件 + 浸透率イベント2件


def test_idempotent(master_conn):
    load_sellin(master_conn, f"{DATA_DIR}/sellin_data.csv")
    load_sellin(master_conn, f"{DATA_DIR}/sellin_data.csv")
    cur = master_conn.execute("SELECT COUNT(*) FROM sellin_data")
    assert cur.fetchone()[0] == 861

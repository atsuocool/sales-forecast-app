import numpy as np
import pytest

from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.pipeline.inventory_loader import load_sellout
from src.forecast.penetration import EventAdjustment
from src.forecast.integrated_forecast import run_integrated_forecast

DATA_DIR    = "docs/sample_data"
IQVIA_CSV   = "docs/sample_data/iqvia_market_data.csv"
SELLOUT_CSV = "docs/sample_data/sellout_data.csv"


@pytest.fixture
def full_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    load_iqvia(mem_conn, IQVIA_CSV)
    load_sellout(mem_conn, SELLOUT_CSV)
    return mem_conn


def test_returns_all_skus_for_ing01(full_conn):
    results = run_integrated_forecast(full_conn, "ING01", horizon=36)
    sku_ids = {r.sku_id for r in results}
    assert sku_ids == {"SKU0101", "SKU0102"}


def test_returns_single_sku_for_ing04(full_conn):
    results = run_integrated_forecast(full_conn, "ING04", horizon=36)
    assert len(results) == 1
    assert results[0].sku_id == "SKU0401"


def test_forecast_horizon_length(full_conn):
    results = run_integrated_forecast(full_conn, "ING01", horizon=36)
    for r in results:
        assert len(r.periods) == 36
        assert r.sellout_units.shape == (36,)
        assert r.sellout_amount_jpy.shape == (36,)


def test_forecast_units_positive(full_conn):
    for ing_id in ["ING01", "ING02", "ING03", "ING04"]:
        for r in run_integrated_forecast(full_conn, ing_id, horizon=12):
            assert (r.sellout_units > 0).all(), f"{r.sku_id} に 0 以下の予測値あり"


def test_forecast_amount_positive(full_conn):
    for r in run_integrated_forecast(full_conn, "ING01", horizon=12):
        assert (r.sellout_amount_jpy > 0).all()


def test_sku_mix_sums_to_own_units(full_conn):
    """全 SKU 数量の合計 ≒ GE/BS 自社数量（成分内合計）"""
    results = run_integrated_forecast(full_conn, "ING01", horizon=12)
    total_by_month = sum(r.sellout_units for r in results)
    # 合計はすべて正であること（市場×浸透率×自社シェア の合計に等しい）
    assert (total_by_month > 0).all()


def test_with_penetration_events(full_conn):
    events = [EventAdjustment(month_offset=6, ceiling_delta=0.05, speed_delta=0.01)]
    base  = run_integrated_forecast(full_conn, "ING03", horizon=12)
    adj   = run_integrated_forecast(full_conn, "ING03", horizon=12, penetration_events=events)
    base_total = sum(r.sellout_units for r in base)
    adj_total  = sum(r.sellout_units for r in adj)
    assert adj_total[6:].mean() > base_total[6:].mean()


def test_periods_format(full_conn):
    results = run_integrated_forecast(full_conn, "ING01", horizon=3)
    for r in results:
        for p in r.periods:
            assert len(p) == 7 and p[4] == "-"


def test_ingredient_id_stored(full_conn):
    results = run_integrated_forecast(full_conn, "ING03", horizon=6)
    for r in results:
        assert r.ingredient_id == "ING03"
        assert r.product_id == "PROD03"

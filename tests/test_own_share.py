import numpy as np
import pytest

from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.forecast.own_share import aggregate_own_share, OwnShareForecaster

DATA_DIR  = "docs/sample_data"
IQVIA_CSV = "docs/sample_data/iqvia_market_data.csv"


@pytest.fixture
def market_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    load_iqvia(mem_conn, IQVIA_CSV)
    return mem_conn


def test_aggregate_own_share_columns(market_conn):
    df = aggregate_own_share(market_conn, "ING01")
    assert set(["period", "own_units", "ge_bs_units", "own_share_ratio"]).issubset(df.columns)


def test_own_share_ratio_in_range(market_conn):
    for ing_id in ["ING01", "ING02", "ING03", "ING04"]:
        df = aggregate_own_share(market_conn, ing_id)
        assert (df["own_share_ratio"] >= 0).all()
        assert (df["own_share_ratio"] <= 1).all()


def test_own_share_ratio_less_than_one(market_conn):
    df = aggregate_own_share(market_conn, "ING01")
    assert (df["own_share_ratio"] < 1).all(), "自社が全GE/BS市場を占めることはない"


def test_own_share_ge_bs_units_gte_own(market_conn):
    df = aggregate_own_share(market_conn, "ING01")
    assert (df["ge_bs_units"] >= df["own_units"]).all()


def test_own_share_forecaster_predict_shape(market_conn):
    df = aggregate_own_share(market_conn, "ING01")
    fc = OwnShareForecaster("ING01").fit(df).predict(36)
    assert fc.shape == (36,)


def test_own_share_forecaster_predict_in_range(market_conn):
    for ing_id in ["ING01", "ING02", "ING03", "ING04"]:
        df = aggregate_own_share(market_conn, ing_id)
        fc = OwnShareForecaster(ing_id).fit(df).predict(36)
        assert (fc >= 0).all() and (fc <= 1).all()


def test_own_share_predict_before_fit_raises():
    with pytest.raises(RuntimeError, match="fit"):
        OwnShareForecaster("ING01").predict(36)

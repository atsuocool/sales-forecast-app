import numpy as np
import pytest

from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.forecast.market_forecast import aggregate_market
from src.forecast.penetration import (
    logistic,
    PenetrationParams,
    EventAdjustment,
    PenetrationForecaster,
)

DATA_DIR = "docs/sample_data"
IQVIA_CSV = "docs/sample_data/iqvia_market_data.csv"


@pytest.fixture
def market_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    load_iqvia(mem_conn, IQVIA_CSV)
    return mem_conn


# --- logistic 関数 ---

def test_logistic_at_inflection():
    L, k, t0 = 0.8, 0.2, 20.0
    assert abs(logistic(np.array([t0]), L, k, t0)[0] - L / 2) < 1e-10


def test_logistic_asymptotes():
    L, k, t0 = 0.8, 0.5, 10.0
    assert logistic(np.array([-1000.0]), L, k, t0)[0] < 0.001
    assert logistic(np.array([1000.0]),  L, k, t0)[0] > L * 0.999


# --- フィッティング ---

def test_fit_ing03_r_squared(market_conn):
    df = aggregate_market(market_conn, "ING03")
    r  = PenetrationForecaster("ING03").fit(df).get_fit_result()
    assert r.r_squared > 0.9
    assert 0.0 < r.params.L <= 1.0
    assert r.params.k > 0


def test_fit_ing04_r_squared(market_conn):
    df = aggregate_market(market_conn, "ING04")
    r  = PenetrationForecaster("ING04").fit(df).get_fit_result()
    assert r.r_squared > 0.9
    assert 0.0 < r.params.L <= 1.0


# --- 予測 ---

def test_predict_shape_and_range(market_conn):
    df = aggregate_market(market_conn, "ING03")
    fc = PenetrationForecaster("ING03").fit(df).predict(horizon=36)
    assert fc.shape == (36,)
    assert (fc >= 0).all() and (fc <= 1).all()


def test_predict_starts_near_last_actual(market_conn):
    df  = aggregate_market(market_conn, "ING03")
    fc  = PenetrationForecaster("ING03").fit(df).predict(horizon=1)
    last = df["penetration_rate"].iloc[-1]
    assert abs(fc[0] - last) < 0.05


def test_params_override(market_conn):
    df  = aggregate_market(market_conn, "ING03")
    f   = PenetrationForecaster("ING03").fit(df)
    base_params = f.get_fit_result().params
    override    = PenetrationParams(L=0.99, k=base_params.k, t0=base_params.t0)
    assert f.predict(horizon=36, params_override=override).mean() > f.predict(horizon=36).mean()


# --- イベント調整 ---

def test_event_raises_ceiling(market_conn):
    df   = aggregate_market(market_conn, "ING03")
    f    = PenetrationForecaster("ING03").fit(df)
    base = f.predict(horizon=36)
    adj  = f.predict(horizon=36, events=[EventAdjustment(month_offset=6, ceiling_delta=0.10)])
    assert adj[6:].mean() > base[6:].mean()


def test_event_no_effect_before_month(market_conn):
    df   = aggregate_market(market_conn, "ING03")
    f    = PenetrationForecaster("ING03").fit(df)
    base = f.predict(horizon=36)
    adj  = f.predict(horizon=36, events=[EventAdjustment(month_offset=12, ceiling_delta=0.10)])
    np.testing.assert_array_almost_equal(base[:11], adj[:11])


# --- エラーケース ---

def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError, match="fit"):
        PenetrationForecaster("ING03").predict(horizon=12)


def test_get_fit_result_before_fit_raises():
    with pytest.raises(RuntimeError, match="fit"):
        PenetrationForecaster("ING03").get_fit_result()

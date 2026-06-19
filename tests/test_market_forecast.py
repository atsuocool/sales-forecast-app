import numpy as np
import pytest
import sqlite3

from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.forecast.metrics import mape, rmse
from src.forecast.market_forecast import (
    aggregate_market,
    MarketForecaster,
    ForecastResult,
    backtest,
    BacktestResult,
)

DATA_DIR = "docs/sample_data"
IQVIA_CSV = "docs/sample_data/iqvia_market_data.csv"
ING_ID = "ING01"


@pytest.fixture
def market_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    load_iqvia(mem_conn, IQVIA_CSV)
    return mem_conn


# --- metrics ---

def test_mape_exact():
    actual    = np.array([100.0, 200.0, 50.0])
    predicted = np.array([110.0, 180.0, 55.0])
    expected  = (10/100 + 20/200 + 5/50) / 3 * 100
    assert abs(mape(actual, predicted) - expected) < 1e-6


def test_mape_ignores_zero_actual():
    actual    = np.array([0.0, 100.0])
    predicted = np.array([99.0, 110.0])
    assert abs(mape(actual, predicted) - 10.0) < 1e-6


def test_rmse_exact():
    actual    = np.array([1.0, 2.0, 3.0])
    predicted = np.array([1.0, 2.0, 4.0])
    assert abs(rmse(actual, predicted) - np.sqrt(1/3)) < 1e-6


# --- aggregate_market ---

def test_aggregate_market_shape(market_conn):
    df = aggregate_market(market_conn, ING_ID)
    assert len(df) == 41
    assert set(df.columns) >= {"period", "total_units", "total_amount_jpy", "penetration_rate"}


def test_aggregate_market_sorted(market_conn):
    df = aggregate_market(market_conn, ING_ID)
    assert list(df["period"]) == sorted(df["period"].tolist())


def test_aggregate_market_sums_all_manufacturers(market_conn):
    df = aggregate_market(market_conn, ING_ID)
    # 2023-01: オリジナル124593 + 競合A238914 + 競合B174277 + 自社65873 = 603657
    row = df[df["period"] == "2023-01"].iloc[0]
    assert abs(row["total_units"] - 603657.0) < 1.0


def test_aggregate_market_positive(market_conn):
    df = aggregate_market(market_conn, ING_ID)
    assert (df["total_units"] > 0).all()
    assert (df["total_amount_jpy"] > 0).all()


# --- MarketForecaster ---

def test_forecaster_predict_shape(market_conn):
    df     = aggregate_market(market_conn, ING_ID)
    result = MarketForecaster(ING_ID, horizon=36).fit(df).predict()
    assert isinstance(result, ForecastResult)
    assert len(result.periods)            == 36
    assert result.forecast_units.shape   == (36,)
    assert result.forecast_amount_jpy.shape == (36,)
    assert result.lower_units.shape      == (36,)
    assert result.upper_units.shape      == (36,)


def test_forecaster_periods_sequential(market_conn):
    df     = aggregate_market(market_conn, ING_ID)
    result = MarketForecaster(ING_ID, horizon=3).fit(df).predict()
    assert result.periods[0] == "2026-06"
    assert result.periods[1] == "2026-07"
    assert result.periods[2] == "2026-08"


def test_forecaster_non_negative(market_conn):
    df     = aggregate_market(market_conn, ING_ID)
    result = MarketForecaster(ING_ID).fit(df).predict()
    assert (result.forecast_units      >= 0).all()
    assert (result.lower_units         >= 0).all()
    assert (result.lower_units         <= result.forecast_units).all()
    assert (result.upper_units         >= result.forecast_units).all()


def test_forecaster_fit_required():
    with pytest.raises(RuntimeError, match="fit"):
        MarketForecaster(ING_ID).predict()


# --- backtest ---

def test_backtest_split(market_conn):
    result = backtest(market_conn, ING_ID, test_periods=12)
    assert result.train_periods == 29
    assert result.test_periods  == 12


def test_backtest_mape_reasonable(market_conn):
    result = backtest(market_conn, ING_ID, test_periods=12)
    assert result.mape_units  < 50.0
    assert result.rmse_units  > 0.0
    assert result.mape_amount < 50.0


def test_backtest_dataframes(market_conn):
    result = backtest(market_conn, ING_ID, test_periods=12)
    assert len(result.actual)    == 12
    assert len(result.predicted) == 12
    assert list(result.actual.columns)    == ["period", "total_units", "total_amount_jpy"]
    assert list(result.predicted.columns) == ["period", "forecast_units", "forecast_amount_jpy"]
    assert result.actual["period"].iloc[0]    == "2025-06"
    assert result.predicted["period"].iloc[0] == "2025-06"


def test_backtest_all_ingredients(market_conn):
    for ing_id in ["ING01", "ING02", "ING03", "ING04"]:
        result = backtest(market_conn, ing_id, test_periods=12)
        assert isinstance(result, BacktestResult)
        assert result.mape_units < 50.0


def test_backtest_insufficient_data(market_conn):
    with pytest.raises(ValueError, match="Not enough data"):
        backtest(market_conn, ING_ID, test_periods=100)

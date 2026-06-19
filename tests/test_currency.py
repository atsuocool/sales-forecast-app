import numpy as np
import pytest

from src.db.schema import create_all_tables
from src.pipeline.fx_loader import load_fx_rates
from src.forecast.currency import (
    get_forecast_rate,
    convert_amounts,
    format_amount,
    DEFAULT_RATE_JPY_PER_USD,
)

FX_CSV = "docs/sample_data/fx_rates_sample.csv"


@pytest.fixture
def fx_conn(mem_conn):
    create_all_tables(mem_conn)
    load_fx_rates(mem_conn, FX_CSV)
    return mem_conn


# --- fx_loader ---

def test_load_fx_rates_count(fx_conn):
    n = fx_conn.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0]
    assert n == 15  # サンプル CSV 行数


def test_load_fx_rates_idempotent(fx_conn):
    load_fx_rates(fx_conn, FX_CSV)
    n = fx_conn.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0]
    assert n == 15


def test_forecast_assumption_loaded(fx_conn):
    row = fx_conn.execute(
        "SELECT jpy_per_usd FROM fx_rates WHERE rate_type='forecast_assumption'"
    ).fetchone()
    assert row is not None
    assert row[0] == 148.0


# --- get_forecast_rate ---

def test_get_forecast_rate_returns_forecast_assumption(fx_conn):
    rate = get_forecast_rate(fx_conn)
    assert rate == 148.0


def test_get_forecast_rate_fallback_to_historical(mem_conn):
    create_all_tables(mem_conn)
    mem_conn.execute(
        "INSERT INTO fx_rates (rate_type, period, jpy_per_usd) VALUES ('historical', '2026-04', 143.8)"
    )
    mem_conn.commit()
    rate = get_forecast_rate(mem_conn)
    assert rate == 143.8


def test_get_forecast_rate_fallback_to_default(mem_conn):
    create_all_tables(mem_conn)
    rate = get_forecast_rate(mem_conn)
    assert rate == DEFAULT_RATE_JPY_PER_USD


# --- convert_amounts ---

def test_convert_jpy_identity():
    arr = np.array([1_000_000.0, 2_000_000.0])
    result = convert_amounts(arr, "JPY", 150.0)
    np.testing.assert_array_equal(result, arr)


def test_convert_usd():
    arr = np.array([150_000.0, 300_000.0])
    result = convert_amounts(arr, "USD", 150.0)
    np.testing.assert_allclose(result, [1_000.0, 2_000.0])


def test_convert_usd_rate_sensitivity():
    arr = np.array([150_000.0])
    r120 = convert_amounts(arr, "USD", 120.0)[0]
    r160 = convert_amounts(arr, "USD", 160.0)[0]
    assert r120 > r160  # 円高 → USD 換算額が大きい


def test_convert_invalid_currency():
    with pytest.raises(ValueError, match="未対応"):
        convert_amounts(np.array([1.0]), "EUR", 150.0)


def test_convert_does_not_mutate_input():
    arr = np.array([100_000.0])
    original = arr.copy()
    convert_amounts(arr, "USD", 150.0)
    np.testing.assert_array_equal(arr, original)


# --- format_amount ---

def test_format_jpy():
    assert format_amount(1_500_000.0, "JPY") == "¥1,500,000"


def test_format_usd():
    assert format_amount(10_000.0, "USD") == "$10,000"

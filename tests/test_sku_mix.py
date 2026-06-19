import numpy as np
import pytest

from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.pipeline.inventory_loader import load_sellout
from src.forecast.sku_mix import aggregate_sellout_by_sku, SkuMixForecaster

DATA_DIR    = "docs/sample_data"
SELLOUT_CSV = "docs/sample_data/sellout_data.csv"


@pytest.fixture
def sellout_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    load_sellout(mem_conn, SELLOUT_CSV)
    return mem_conn


def test_aggregate_sellout_columns(sellout_conn):
    df = aggregate_sellout_by_sku(sellout_conn, "PROD01")
    assert set(["period", "sku_id", "total_qty", "mix_ratio"]).issubset(df.columns)


def test_mix_ratio_sums_to_one_per_period(sellout_conn):
    df = aggregate_sellout_by_sku(sellout_conn, "PROD01")
    period_sums = df.groupby("period")["mix_ratio"].sum()
    assert (abs(period_sums - 1.0) < 1e-9).all()


def test_mix_ratio_non_negative(sellout_conn):
    for prod_id in ["PROD01", "PROD02", "PROD03", "PROD04"]:
        df = aggregate_sellout_by_sku(sellout_conn, prod_id)
        assert (df["mix_ratio"] >= 0).all()


def test_aggregate_single_sku_product(sellout_conn):
    df = aggregate_sellout_by_sku(sellout_conn, "PROD04")
    period_sums = df.groupby("period")["mix_ratio"].sum()
    assert (abs(period_sums - 1.0) < 1e-9).all()
    assert (df["mix_ratio"] == 1.0).all()


def test_sku_mix_forecast_shape(sellout_conn):
    df  = aggregate_sellout_by_sku(sellout_conn, "PROD01")
    out = SkuMixForecaster("PROD01").fit(df).predict(36)
    sku_ids = df["sku_id"].unique()
    assert len(out) == 36 * len(sku_ids)
    assert "month_offset" in out.columns
    assert "forecast_mix_ratio" in out.columns


def test_sku_mix_forecast_normalized(sellout_conn):
    df  = aggregate_sellout_by_sku(sellout_conn, "PROD01")
    out = SkuMixForecaster("PROD01").fit(df).predict(36)
    month_sums = out.groupby("month_offset")["forecast_mix_ratio"].sum()
    assert (abs(month_sums - 1.0) < 1e-9).all()


def test_sku_mix_forecast_non_negative(sellout_conn):
    df  = aggregate_sellout_by_sku(sellout_conn, "PROD01")
    out = SkuMixForecaster("PROD01").fit(df).predict(36)
    assert (out["forecast_mix_ratio"] >= 0).all()


def test_sku_mix_predict_before_fit_raises():
    with pytest.raises(RuntimeError, match="fit"):
        SkuMixForecaster("PROD01").predict(36)

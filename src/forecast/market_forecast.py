import sqlite3
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.forecast.metrics import mape, rmse


def aggregate_market(conn: sqlite3.Connection, ingredient_id: str) -> pd.DataFrame:
    """
    market_data テーブルから全メーカー区分を合算し、成分×月次の総市場量を返す。
    columns: period(str), total_units(float), total_amount_jpy(float), penetration_rate(float)
    period 昇順ソート済み。
    """
    return pd.read_sql(
        """
        SELECT period,
               SUM(sales_units)                          AS total_units,
               SUM(sales_amount_jpy)                     AS total_amount_jpy,
               MAX(generic_biosimilar_penetration_rate)  AS penetration_rate
        FROM market_data
        WHERE ingredient_id = ?
        GROUP BY period
        ORDER BY period
        """,
        conn,
        params=[ingredient_id],
    )


@dataclass
class ForecastResult:
    ingredient_id:       str
    periods:             List[str]
    forecast_units:      np.ndarray
    forecast_amount_jpy: np.ndarray
    lower_units:         np.ndarray
    upper_units:         np.ndarray


class MarketForecaster:
    """
    Holt-Winters 指数平滑法で成分市場の数量・金額を予測する。
    訓練データ >= 24ヶ月なら季節成分（seasonal_periods=12）を追加、未満は線形トレンドのみ。
    80% 予測区間は残差標準偏差の累積誤差近似（±1.28σ√h）で計算。
    """
    MIN_SEASONAL_MONTHS = 24
    SEASONAL_PERIODS    = 12

    def __init__(self, ingredient_id: str, horizon: int = 36):
        self.ingredient_id = ingredient_id
        self.horizon       = horizon
        self._fit_units:   Optional[object] = None
        self._fit_amount:  Optional[object] = None
        self._last_period: Optional[str]    = None
        self._std_units:   Optional[float]  = None
        self._std_amount:  Optional[float]  = None

    def fit(self, df: pd.DataFrame) -> "MarketForecaster":
        """
        df: aggregate_market() の出力（period 昇順ソート済み）。
        columns 必須: total_units, total_amount_jpy
        """
        use_seasonal = len(df) >= self.MIN_SEASONAL_MONTHS

        def _fit(series: pd.Series):
            kwargs = dict(trend="add", initialization_method="estimated")
            if use_seasonal:
                kwargs["seasonal"]         = "add"
                kwargs["seasonal_periods"] = self.SEASONAL_PERIODS
            return ExponentialSmoothing(series, **kwargs).fit(optimized=True)

        self._fit_units   = _fit(df["total_units"])
        self._fit_amount  = _fit(df["total_amount_jpy"])
        self._last_period = df["period"].iloc[-1]
        self._std_units   = float(np.std(self._fit_units.resid,  ddof=1))
        self._std_amount  = float(np.std(self._fit_amount.resid, ddof=1))
        return self

    def _next_periods(self) -> List[str]:
        year, month = int(self._last_period[:4]), int(self._last_period[5:7])
        periods = []
        for _ in range(self.horizon):
            month += 1
            if month > 12:
                month, year = 1, year + 1
            periods.append(f"{year:04d}-{month:02d}")
        return periods

    def predict(self) -> ForecastResult:
        """fit() 後に呼ぶ。horizon ステップ先の点予測 + 80% 予測区間を返す。"""
        if self._fit_units is None:
            raise RuntimeError("predict() の前に fit() を呼んでください")

        fc_units  = self._fit_units.forecast(self.horizon).values
        fc_amount = self._fit_amount.forecast(self.horizon).values

        h = np.arange(1, self.horizon + 1)
        margin_units  = 1.28 * self._std_units  * np.sqrt(h)

        return ForecastResult(
            ingredient_id       = self.ingredient_id,
            periods             = self._next_periods(),
            forecast_units      = np.maximum(fc_units,  0),
            forecast_amount_jpy = np.maximum(fc_amount, 0),
            lower_units         = np.maximum(fc_units - margin_units, 0),
            upper_units         = np.maximum(fc_units + margin_units, 0),
        )


@dataclass
class BacktestResult:
    ingredient_id: str
    train_periods: int
    test_periods:  int
    mape_units:    float
    rmse_units:    float
    mape_amount:   float
    rmse_amount:   float
    actual:        pd.DataFrame   # period, total_units, total_amount_jpy
    predicted:     pd.DataFrame   # period, forecast_units, forecast_amount_jpy


def backtest(
    conn:          sqlite3.Connection,
    ingredient_id: str,
    test_periods:  int = 12,
    horizon:       int = 36,
) -> BacktestResult:
    """
    直近 test_periods ヶ月をhold-outとし、Holt-Wintersの予測精度を評価する。
    """
    df = aggregate_market(conn, ingredient_id)
    if len(df) <= test_periods:
        raise ValueError(
            f"Not enough data: {len(df)} periods <= test_periods={test_periods}"
        )

    df_train = df.iloc[:-test_periods].reset_index(drop=True)
    df_test  = df.iloc[-test_periods:].reset_index(drop=True)

    fc = MarketForecaster(ingredient_id, horizon=test_periods).fit(df_train).predict()

    act_units  = df_test["total_units"].values
    act_amount = df_test["total_amount_jpy"].values

    return BacktestResult(
        ingredient_id = ingredient_id,
        train_periods = len(df_train),
        test_periods  = test_periods,
        mape_units    = mape(act_units,  fc.forecast_units),
        rmse_units    = rmse(act_units,  fc.forecast_units),
        mape_amount   = mape(act_amount, fc.forecast_amount_jpy),
        rmse_amount   = rmse(act_amount, fc.forecast_amount_jpy),
        actual    = df_test[["period", "total_units", "total_amount_jpy"]].copy(),
        predicted = pd.DataFrame({
            "period":              fc.periods[:test_periods],
            "forecast_units":      fc.forecast_units,
            "forecast_amount_jpy": fc.forecast_amount_jpy,
        }),
    )

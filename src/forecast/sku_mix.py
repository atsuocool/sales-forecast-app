import sqlite3
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd


def aggregate_sellout_by_sku(conn: sqlite3.Connection, product_id: str) -> pd.DataFrame:
    """
    sellout_data から製品内 SKU 構成比を月次集計する。
    施設区分（facility_type）を合算し、SKU 単位の数量比率を算出。

    Returns: period(str), sku_id(str), total_qty(float), mix_ratio(float)
    mix_ratio は同月内の全 SKU 合計が 1.0 になるよう正規化済み。
    """
    df = pd.read_sql(
        """
        SELECT sd.period,
               sd.sku_id,
               SUM(sd.quantity) AS total_qty
        FROM sellout_data sd
        JOIN skus s ON sd.sku_id = s.sku_id
        WHERE s.product_id = ?
        GROUP BY sd.period, sd.sku_id
        ORDER BY sd.period, sd.sku_id
        """,
        conn,
        params=[product_id],
    )

    period_totals = (
        df.groupby("period")["total_qty"].sum().rename("period_total")
    )
    df = df.join(period_totals, on="period")
    df["mix_ratio"] = np.where(
        df["period_total"] > 0,
        df["total_qty"] / df["period_total"],
        0.0,
    )
    return df.drop(columns=["period_total"])


@dataclass
class SkuMixTrend:
    sku_id:    str
    slope:     float   # 月次トレンド傾き
    intercept: float   # t=0 時点の構成比


class SkuMixForecaster:
    """
    線形トレンドで各 SKU の構成比（ミックス比率）を予測する。
    予測後に月次合計が 1.0 になるよう正規化を行う。
    fit() → predict() の順で使用。
    """

    def __init__(self, product_id: str):
        self.product_id = product_id
        self._trends:  Optional[List[SkuMixTrend]] = None
        self._n_train: int = 0

    def fit(self, df: pd.DataFrame) -> "SkuMixForecaster":
        """
        df: aggregate_sellout_by_sku() の出力。
        必須列: period(str), sku_id(str), mix_ratio(float)
        """
        periods        = sorted(df["period"].unique())
        period_to_t    = {p: i for i, p in enumerate(periods)}
        self._n_train  = len(periods)
        sku_ids        = sorted(df["sku_id"].unique())

        trends = []
        for sku_id in sku_ids:
            sub = df[df["sku_id"] == sku_id].copy()
            sub["t"] = sub["period"].map(period_to_t)
            t = sub["t"].values.astype(float)
            y = sub["mix_ratio"].values.astype(float)
            if len(t) >= 2:
                slope, intercept = np.polyfit(t, y, 1)
            else:
                slope, intercept = 0.0, float(y.mean())
            trends.append(SkuMixTrend(sku_id=sku_id, slope=slope, intercept=intercept))

        self._trends = trends
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        """
        horizon ヶ月分の SKU 構成比予測を返す。
        月次で全 SKU の合計が 1.0 になるよう正規化する。

        Returns: month_offset(int 0始まり), sku_id(str), forecast_mix_ratio(float)
        """
        if self._trends is None:
            raise RuntimeError("predict() の前に fit() を呼んでください")

        n    = self._n_train
        t_fc = np.arange(n, n + horizon, dtype=float)

        records = []
        for trend in self._trends:
            raw = np.clip(trend.intercept + trend.slope * t_fc, 0.0, 1.0)
            for i, val in enumerate(raw):
                records.append({"month_offset": i, "sku_id": trend.sku_id, "raw": val})

        result = pd.DataFrame(records)
        month_total = result.groupby("month_offset")["raw"].sum().rename("total")
        result = result.join(month_total, on="month_offset")
        result["forecast_mix_ratio"] = np.where(
            result["total"] > 0,
            result["raw"] / result["total"],
            1.0 / len(self._trends),
        )
        return result[["month_offset", "sku_id", "forecast_mix_ratio"]].reset_index(drop=True)

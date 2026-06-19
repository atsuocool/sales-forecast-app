import sqlite3
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


def aggregate_own_share(conn: sqlite3.Connection, ingredient_id: str) -> pd.DataFrame:
    """
    IQVIA market_data から自社シェア（成分内 GE/BS 中の自社比率）を集計する。
    GE/BS = manufacturer_type が「オリジナル」以外のすべて。

    Returns: period(str), own_units(float), ge_bs_units(float), own_share_ratio(float)
    """
    df = pd.read_sql(
        """
        SELECT period,
               SUM(CASE WHEN manufacturer_type = '自社'
                        THEN sales_units ELSE 0 END)   AS own_units,
               SUM(CASE WHEN manufacturer_type != 'オリジナル'
                        THEN sales_units ELSE 0 END)   AS ge_bs_units
        FROM market_data
        WHERE ingredient_id = ?
        GROUP BY period
        ORDER BY period
        """,
        conn,
        params=[ingredient_id],
    )
    df["own_share_ratio"] = np.where(
        df["ge_bs_units"] > 0,
        df["own_units"] / df["ge_bs_units"],
        0.0,
    )
    return df


@dataclass
class OwnShareParams:
    slope:     float   # 月次トレンド傾き（正=上昇、負=低下）
    intercept: float   # t=0 時点の自社シェア


class OwnShareForecaster:
    """
    線形トレンドで自社 GE/BS シェアを予測する。
    fit() → predict() の順で使用。
    """

    def __init__(self, ingredient_id: str):
        self.ingredient_id = ingredient_id
        self._params:  Optional[OwnShareParams] = None
        self._n_train: int = 0

    def fit(self, df: pd.DataFrame) -> "OwnShareForecaster":
        """
        df: aggregate_own_share() の出力。
        必須列: own_share_ratio（0〜1 の浮動小数点）
        """
        series = df["own_share_ratio"].values.astype(float)
        t      = np.arange(len(series), dtype=float)
        slope, intercept = np.polyfit(t, series, 1)
        self._params  = OwnShareParams(slope=slope, intercept=intercept)
        self._n_train = len(series)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        """horizon ヶ月分の自社シェア予測値（0〜1）を返す。"""
        if self._params is None:
            raise RuntimeError("predict() の前に fit() を呼んでください")
        t_fc = np.arange(self._n_train, self._n_train + horizon, dtype=float)
        return np.clip(
            self._params.intercept + self._params.slope * t_fc,
            0.0,
            1.0,
        )

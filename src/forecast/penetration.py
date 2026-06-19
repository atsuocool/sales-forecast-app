from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


def logistic(t: np.ndarray, L: float, k: float, t0: float) -> np.ndarray:
    """S字カーブ: P(t) = L / (1 + exp(−k·(t−t0)))"""
    return L / (1 + np.exp(-k * (t - t0)))


@dataclass
class PenetrationParams:
    L: float   # 浸透率上限（飽和点）0〜1
    k: float   # 立ち上がり速度（月次）
    t0: float  # 変曲点タイミング（t=0 からの月数）


@dataclass
class EventAdjustment:
    """制度変更イベントによるパラメータ調整"""
    month_offset: int           # 予測開始月からの月数（1始まり）
    ceiling_delta: float = 0.0  # L への加算値（例: +0.05 → 上限+5pp）
    speed_delta: float = 0.0    # k への加算値（例: +0.01 → 速度上昇）
    label: str = ""             # プロット用ラベル


@dataclass
class PenetrationFitResult:
    ingredient_id: str
    params:        PenetrationParams
    t_values:      np.ndarray   # 訓練データの t インデックス（0始まり）
    actual:        np.ndarray   # 実績浸透率
    fitted:        np.ndarray   # フィット値
    r_squared:     float
    start_period:  str          # t=0 に対応する YYYY-MM


class PenetrationForecaster:
    """
    ロジスティック曲線（scipy.optimize.curve_fit）で成分別浸透率を予測。
    fit() → predict() の順で使用する。

    logistic: P(t) = L / (1 + exp(−k·(t−t0)))
      L  = 浸透率上限（飽和点）
      k  = 立ち上がり速度
      t0 = 変曲点（P = L/2 となる月インデックス）
    """

    def __init__(self, ingredient_id: str):
        self.ingredient_id    = ingredient_id
        self._params:         Optional[PenetrationParams] = None
        self._n_train:        int = 0
        self._start_period:   str = ""
        self._fit_t:          Optional[np.ndarray] = None
        self._fit_series:     Optional[np.ndarray] = None
        self._fitted:         Optional[np.ndarray] = None
        self._r2:             float = 0.0

    def fit(self, df: pd.DataFrame) -> "PenetrationForecaster":
        """
        df: aggregate_market() の出力。
        必須列: period(str YYYY-MM昇順), penetration_rate(float 0〜1)
        """
        series = df["penetration_rate"].values.astype(float)
        t      = np.arange(len(series), dtype=float)
        n      = len(series)

        L_init = min(series[-1] * 1.4, 0.99)
        p0     = [L_init, 0.08, float(n // 2)]
        bounds = ([0.01, 0.001, -float(n)], [1.0, 5.0, float(2 * n)])

        popt, _ = curve_fit(
            logistic, t, series, p0=p0, bounds=bounds, maxfev=20000
        )

        fitted = logistic(t, *popt)
        ss_res = float(np.sum((series - fitted) ** 2))
        ss_tot = float(np.sum((series - series.mean()) ** 2))
        r2     = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        self._params       = PenetrationParams(L=popt[0], k=popt[1], t0=popt[2])
        self._n_train      = n
        self._start_period = df["period"].iloc[0]
        self._fit_t        = t
        self._fit_series   = series
        self._fitted       = fitted
        self._r2           = r2
        return self

    def get_fit_result(self) -> PenetrationFitResult:
        if self._params is None:
            raise RuntimeError("get_fit_result() の前に fit() を呼んでください")
        return PenetrationFitResult(
            ingredient_id = self.ingredient_id,
            params        = self._params,
            t_values      = self._fit_t,
            actual        = self._fit_series,
            fitted        = self._fitted,
            r_squared     = self._r2,
            start_period  = self._start_period,
        )

    def predict(
        self,
        horizon:         int,
        params_override: Optional[PenetrationParams] = None,
        events:          Optional[List[EventAdjustment]] = None,
    ) -> np.ndarray:
        """
        horizon 月分の浸透率予測値（0〜1）を返す。
        params_override: L/k/t0 を上書きしたい場合に指定。
        events: 制度変更イベントリスト。month_offset 月目以降の L・k を調整する。
                イベント前の値は変更しない（month_offset 未満のインデックスは不変）。
        """
        if self._params is None:
            raise RuntimeError("predict() の前に fit() を呼んでください")

        p    = params_override if params_override is not None else self._params
        n    = self._n_train
        t_fc = np.arange(n, n + horizon, dtype=float)

        L, k, t0 = p.L, p.k, p.t0
        forecast = logistic(t_fc, L, k, t0).copy()

        if events:
            for ev in sorted(events, key=lambda e: e.month_offset):
                idx = ev.month_offset - 1   # 0-based in forecast array
                if idx >= horizon:
                    continue
                L = min(L + ev.ceiling_delta, 1.0)
                k = k + ev.speed_delta
                forecast[idx:] = logistic(t_fc[idx:], L, k, t0)

        return np.clip(forecast, 0.0, 1.0)

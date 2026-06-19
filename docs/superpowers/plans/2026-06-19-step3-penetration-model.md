# Step 3: 浸透率モデル（ロジスティック曲線） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 成分ごとの generic_biosimilar_penetration_rate にロジスティック曲線をフィッティングし、36ヶ月予測と制度変更イベントによるパラメータ調整ロジックを実装。結果をmatplotlibでプロット保存する。

**Architecture:** `PenetrationForecaster` が scipy.optimize.curve_fit でロジスティック関数（L/k/t0）をフィットし、predict() で将来浸透率を返す。`EventAdjustment` リストを渡すと指定月以降のL・kを調整する。プロットはscripts/plot_penetration.py が output/ にPNG保存する。

**Tech Stack:** Python 3.9, scipy 1.13 (curve_fit), matplotlib, numpy, pandas, pytest

## Global Constraints

- Python 3.9: `X | Y` 使用不可 → `Optional[X]` を使う
- 浸透率は 0〜1 の実数（百分率ではない）
- t は訓練データ先頭を 0 とした月インデックス（float）
- LogisticModel: P(t) = L / (1 + exp(−k·(t − t0)))
  - L: 上限（0.01〜1.0）  k: 速度（0.001〜5.0）  t0: 変曲点（−n〜2n）
- イベント調整後のL は min(L + ceiling_delta, 1.0) にクリップ
- R² > 0.9 を ING03・ING04 の合格基準とする

---

## File Structure

```
src/forecast/
  penetration.py          # logistic(), PenetrationParams, EventAdjustment,
                          # PenetrationFitResult, PenetrationForecaster
tests/
  test_penetration.py
scripts/
  plot_penetration.py     # 全4成分の実績 vs フィット vs 予測をPNG出力
output/                   # プロット保存先（gitignore）
requirements.txt          # matplotlib を追加
```

---

### Task 1: `src/forecast/penetration.py` — コアモデル

**Files:**
- Create: `src/forecast/penetration.py`
- Create: `tests/test_penetration.py`
- Modify: `requirements.txt`（matplotlib 追加）
- Create: `output/.gitkeep`

**Interfaces:**
- Consumes: `aggregate_market(conn, ingredient_id)` → DataFrame (period, penetration_rate)
- Produces:
  - `logistic(t: np.ndarray, L: float, k: float, t0: float) -> np.ndarray`
  - `PenetrationParams(L: float, k: float, t0: float)`
  - `EventAdjustment(month_offset: int, ceiling_delta: float=0.0, speed_delta: float=0.0, label: str="")`
  - `PenetrationFitResult(ingredient_id, params, t_values, actual, fitted, r_squared, start_period)`
  - `PenetrationForecaster(ingredient_id: str)`
    - `.fit(df: pd.DataFrame) -> PenetrationForecaster`  ← df は aggregate_market の出力
    - `.get_fit_result() -> PenetrationFitResult`
    - `.predict(horizon: int, params_override=None, events=None) -> np.ndarray`  ← shape (horizon,), 0〜1

- [ ] **Step 1: テストを書く**

`tests/test_penetration.py`:
```python
import numpy as np
import pytest
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.forecast.market_forecast import aggregate_market
from src.forecast.penetration import (
    logistic, PenetrationParams, EventAdjustment,
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


def test_logistic_at_inflection():
    L, k, t0 = 0.8, 0.2, 20.0
    assert abs(logistic(np.array([t0]), L, k, t0)[0] - L / 2) < 1e-10


def test_logistic_asymptotes():
    L, k, t0 = 0.8, 0.5, 10.0
    assert logistic(np.array([-1000.0]), L, k, t0)[0] < 0.001
    assert logistic(np.array([1000.0]),  L, k, t0)[0] > L * 0.999


def test_fit_ing03_r_squared(market_conn):
    df = aggregate_market(market_conn, "ING03")
    r = PenetrationForecaster("ING03").fit(df).get_fit_result()
    assert r.r_squared > 0.9
    assert 0.0 < r.params.L <= 1.0
    assert r.params.k > 0


def test_fit_ing04_r_squared(market_conn):
    df = aggregate_market(market_conn, "ING04")
    r = PenetrationForecaster("ING04").fit(df).get_fit_result()
    assert r.r_squared > 0.9
    assert 0.0 < r.params.L <= 1.0


def test_predict_shape_and_range(market_conn):
    df = aggregate_market(market_conn, "ING03")
    fc = PenetrationForecaster("ING03").fit(df).predict(horizon=36)
    assert fc.shape == (36,)
    assert (fc >= 0).all() and (fc <= 1).all()


def test_predict_starts_near_last_actual(market_conn):
    df = aggregate_market(market_conn, "ING03")
    fc = PenetrationForecaster("ING03").fit(df).predict(horizon=1)
    last_actual = df["penetration_rate"].iloc[-1]
    assert abs(fc[0] - last_actual) < 0.05


def test_event_raises_ceiling(market_conn):
    df = aggregate_market(market_conn, "ING03")
    f = PenetrationForecaster("ING03").fit(df)
    base = f.predict(horizon=36)
    adj  = f.predict(horizon=36, events=[EventAdjustment(month_offset=6, ceiling_delta=0.10)])
    assert adj[6:].mean() > base[6:].mean()


def test_event_no_effect_before_month(market_conn):
    df = aggregate_market(market_conn, "ING03")
    f = PenetrationForecaster("ING03").fit(df)
    base = f.predict(horizon=36)
    adj  = f.predict(horizon=36, events=[EventAdjustment(month_offset=12, ceiling_delta=0.10)])
    np.testing.assert_array_almost_equal(base[:11], adj[:11])


def test_predict_fit_required():
    with pytest.raises(RuntimeError, match="fit"):
        PenetrationForecaster("ING03").predict(horizon=12)


def test_params_override(market_conn):
    df = aggregate_market(market_conn, "ING03")
    f = PenetrationForecaster("ING03").fit(df)
    base_params = f.get_fit_result().params
    # L を 0.99 に上書きすると予測値が高くなるはず
    override = PenetrationParams(L=0.99, k=base_params.k, t0=base_params.t0)
    fc_high = f.predict(horizon=36, params_override=override)
    fc_base = f.predict(horizon=36)
    assert fc_high.mean() > fc_base.mean()
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd ~/projects/sales-forecast-app
python3 -m pytest tests/test_penetration.py -v 2>&1 | head -20
```

Expected: ERROR "cannot import name 'logistic'"

- [ ] **Step 3: requirements.txt を更新してmatplotlibをインストール**

`requirements.txt`:
```
pandas>=2.0
openpyxl>=3.1
pytest>=8.0
numpy>=1.26
statsmodels>=0.14
matplotlib>=3.7
scipy>=1.10
```

```bash
pip3 install matplotlib -q && python3 -c "import matplotlib; print('matplotlib', matplotlib.__version__)"
```

Expected: matplotlib 3.x.x

- [ ] **Step 4: `src/forecast/penetration.py` を実装**

```python
import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit


def logistic(t: np.ndarray, L: float, k: float, t0: float) -> np.ndarray:
    """S字カーブ: P(t) = L / (1 + exp(−k·(t−t0)))"""
    return L / (1 + np.exp(-k * (t - t0)))


@dataclass
class PenetrationParams:
    L: float   # 浸透率上限（飽和点） 0〜1
    k: float   # 立ち上がり速度（月次）
    t0: float  # 変曲点タイミング（t=0 からの月数）


@dataclass
class EventAdjustment:
    """制度変更イベントによるパラメータ調整"""
    month_offset: int          # 予測開始月からの月数（1始まり）
    ceiling_delta: float = 0.0 # L への加算値（例: +0.05 → 上限+5pp）
    speed_delta: float   = 0.0 # k への加算値（例: +0.01 → 速度上昇）
    label: str           = ""  # プロット用ラベル


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
    """

    def __init__(self, ingredient_id: str):
        self.ingredient_id = ingredient_id
        self._params: Optional[PenetrationParams] = None
        self._n_train:       int = 0
        self._start_period:  str = ""
        self._fit_t:         Optional[np.ndarray] = None
        self._fit_series:    Optional[np.ndarray] = None
        self._fitted:        Optional[np.ndarray] = None
        self._r2:            float = 0.0

    def fit(self, df: pd.DataFrame) -> "PenetrationForecaster":
        """
        df: aggregate_market() の出力。
        必須列: period(str, YYYY-MM昇順), penetration_rate(float, 0〜1)
        """
        series = df["penetration_rate"].values.astype(float)
        t      = np.arange(len(series), dtype=float)
        n      = len(series)

        L_init = min(series[-1] * 1.4, 0.99)
        p0     = [L_init, 0.08, float(n // 2)]
        bounds = ([0.01, 0.001, -float(n)], [1.0, 5.0, float(2 * n)])

        popt, _ = curve_fit(logistic, t, series, p0=p0, bounds=bounds, maxfev=20000)

        fitted = logistic(t, *popt)
        ss_res = np.sum((series - fitted) ** 2)
        ss_tot = np.sum((series - series.mean()) ** 2)
        r2     = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

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
            raise RuntimeError("fit() を先に呼んでください")
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
        params_override: L/k/t0 を上書きする場合に指定。
        events: 制度変更イベント。month_offset 月目以降のL・kを調整する。
        """
        if self._params is None:
            raise RuntimeError("predict() の前に fit() を呼んでください")

        p  = params_override if params_override is not None else self._params
        n  = self._n_train
        t_fc = np.arange(n, n + horizon, dtype=float)

        L, k, t0 = p.L, p.k, p.t0
        forecast = logistic(t_fc, L, k, t0)

        if events:
            for ev in sorted(events, key=lambda e: e.month_offset):
                idx = ev.month_offset - 1   # 0-based in forecast array
                if idx >= horizon:
                    continue
                L  = min(L + ev.ceiling_delta, 1.0)
                k  = k + ev.speed_delta
                forecast[idx:] = logistic(t_fc[idx:], L, k, t0)

        return np.clip(forecast, 0.0, 1.0)
```

- [ ] **Step 5: output/.gitkeep と .gitignore 追記**

```bash
mkdir -p ~/projects/sales-forecast-app/output
touch ~/projects/sales-forecast-app/output/.gitkeep
```

`.gitignore` に追記:
```
output/*.png
output/*.pdf
```

- [ ] **Step 6: テストが通ることを確認**

```bash
python3 -m pytest tests/test_penetration.py -v
```

Expected: PASSED (10 tests)

- [ ] **Step 7: Commit**

```bash
git add src/forecast/penetration.py tests/test_penetration.py \
        requirements.txt output/.gitkeep .gitignore
git commit -m "feat: logistic curve penetration forecaster with event adjustment"
```

---

### Task 2: `scripts/plot_penetration.py` — フィット結果の可視化

**Files:**
- Create: `scripts/plot_penetration.py`

**Interfaces:**
- Consumes: `PenetrationForecaster`, `aggregate_market`, `get_connection`
- Produces: `output/penetration_ING03.png`, `output/penetration_ING04.png`, `output/penetration_ING01.png`, `output/penetration_ING02.png`

- [ ] **Step 1: `scripts/plot_penetration.py` を実装**

```python
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from src.db.connection import get_connection
from src.forecast.market_forecast import aggregate_market
from src.forecast.penetration import PenetrationForecaster, EventAdjustment

DB_PATH    = "data/pharma_forecast.db"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def _period_to_date(period: str) -> datetime:
    return datetime.strptime(period + "-01", "%Y-%m-%d")


def _next_periods(last_period: str, n: int):
    year, month = int(last_period[:4]), int(last_period[5:7])
    result = []
    for _ in range(n):
        month += 1
        if month > 12:
            month, year = 1, year + 1
        result.append(f"{year:04d}-{month:02d}")
    return result


def plot_ingredient(
    conn,
    ing_id: str,
    name: str,
    events=None,
    horizon: int = 36,
) -> None:
    df        = aggregate_market(conn, ing_id)
    forecaster = PenetrationForecaster(ing_id).fit(df)
    fit_r     = forecaster.get_fit_result()

    base_fc = forecaster.predict(horizon=horizon)
    adj_fc  = forecaster.predict(horizon=horizon, events=events) if events else None

    actual_dates = [_period_to_date(p) for p in df["period"]]
    fc_periods   = _next_periods(df["period"].iloc[-1], horizon)
    fc_dates     = [_period_to_date(p) for p in fc_periods]

    fig, ax = plt.subplots(figsize=(13, 5))

    # 実績
    ax.plot(actual_dates, df["penetration_rate"],
            "o-", color="#2563EB", linewidth=1.5, markersize=4,
            label="実績", zorder=5)

    # フィット曲線（訓練期間）
    ax.plot(actual_dates, fit_r.fitted,
            "--", color="#16A34A", linewidth=2,
            label=f"フィット (R²={fit_r.r_squared:.3f})")

    # ベース予測
    ax.plot(fc_dates, base_fc,
            "-", color="#DC2626", linewidth=2, label="予測（ベース）")
    ax.fill_between(fc_dates,
                    np.clip(base_fc - 0.03, 0, 1),
                    np.clip(base_fc + 0.03, 0, 1),
                    color="#DC2626", alpha=0.12)

    # 制度変更加味シナリオ
    if adj_fc is not None:
        ax.plot(fc_dates, adj_fc,
                "--", color="#9333EA", linewidth=2, label="予測（制度変更加味）")
        if events:
            for ev in events:
                if ev.month_offset <= horizon:
                    ev_date = _period_to_date(fc_periods[ev.month_offset - 1])
                    ax.axvline(ev_date, color="#9333EA", linestyle=":", alpha=0.6)
                    ax.text(ev_date, 0.97, ev.label or "イベント",
                            color="#9333EA", fontsize=7,
                            ha="center", va="top", transform=ax.get_xaxis_transform())

    # 予測開始境界線
    boundary = _period_to_date(df["period"].iloc[-1])
    ax.axvline(boundary, color="gray", linestyle=":", alpha=0.5)
    ax.text(boundary, 0.02, "予測開始→",
            color="gray", fontsize=8, ha="left", va="bottom")

    p = fit_r.params
    subtitle = f"L={p.L:.3f}（上限）  k={p.k:.4f}（速度）  t₀={p.t0:.1f}ヶ月目（変曲点）"
    ax.set_title(f"{name}（{ing_id}）浸透率 — ロジスティック曲線\n{subtitle}", fontsize=11)
    ax.set_xlabel("月")
    ax.set_ylabel("浸透率（GE/BS シェア）")
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=40, ha="right", fontsize=8)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    out = OUTPUT_DIR / f"penetration_{ing_id}.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {out}")


def main():
    conn = get_connection(DB_PATH)

    # 制度変更加味シナリオ: 後発品使用促進策強化（2027-04: 上限+5pp, 速度+0.01）
    promotion_events = [
        EventAdjustment(month_offset=11, ceiling_delta=0.05,
                        speed_delta=0.01, label="2027-04\n使用促進策"),
    ]

    targets = [
        ("ING03", "フィルグラスチム",    promotion_events),
        ("ING04", "インフリキシマブ",    promotion_events),
        ("ING01", "メトホルミン塩酸塩",  None),
        ("ING02", "アトルバスタチン",    None),
    ]

    print("=" * 60)
    print("浸透率ロジスティックカーブ フィッティング＆予測")
    print("=" * 60)
    for ing_id, name, events in targets:
        df = aggregate_market(conn, ing_id)
        forecaster = PenetrationForecaster(ing_id).fit(df)
        r = forecaster.get_fit_result()
        p = r.params
        print(f"\n{name} ({ing_id})")
        print(f"  L (上限)    = {p.L:.4f} ({p.L:.1%})")
        print(f"  k (速度)    = {p.k:.5f}")
        print(f"  t0 (変曲点) = {p.t0:.1f} ヶ月目 (t=0: {r.start_period})")
        print(f"  R²          = {r.r_squared:.4f}")
        plot_ingredient(conn, ing_id, name, events=events)

    conn.close()
    print("\n完了。output/ フォルダを確認してください。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: スクリプトを実行してプロット確認**

```bash
cd ~/projects/sales-forecast-app
python3 scripts/plot_penetration.py
```

Expected:
```
============================...
フィルグラスチム (ING03)
  L (上限)    = 0.XXXX (XX.X%)
  k (速度)    = 0.XXXXX
  t0 (変曲点) = XX.X ヶ月目 (t=0: 2023-01)
  R²          = 0.XXXX
  → output/penetration_ING03.png
...
完了。output/ フォルダを確認してください。
```

- [ ] **Step 3: 全テストが通ることを確認**

```bash
python3 -m pytest tests/ -v --tb=short -q
```

Expected: 45 passed（既存35 + 新規10）

- [ ] **Step 4: Commit**

```bash
git add scripts/plot_penetration.py
git commit -m "feat: Step 3 complete - logistic penetration forecast with event adjustment + plots"
```

---

## Self-Review

**Spec coverage（仕様書6.1 Step2、8章パラメータ調整）:**
- [x] ロジスティック曲線（S字カーブ）フィッティング → `logistic()` + `curve_fit`
- [x] パラメータ: 浸透率上限(L)・立ち上がり速度(k)・変曲点タイミング(t0) → `PenetrationParams`
- [x] ING03/ING04でのフィッティング確認 → テストで R²>0.9 を検証
- [x] 制度変更イベントで上限・速度を調整可能 → `EventAdjustment` + `predict(events=...)`
- [x] フィッティング結果を実績と重ねてプロット → `plot_penetration.py` → PNG出力
- [x] パラメータ手動上書き → `predict(params_override=...)`（8章のパラメータ調整機能）

**Placeholderスキャン:** なし。全ステップにコードあり。

**型一貫性:**
- `PenetrationForecaster.fit(df)` の `df` は `aggregate_market()` 出力（`penetration_rate` 列あり）
- `get_fit_result()` → `PenetrationFitResult.params` は `PenetrationParams`
- `predict(events=[EventAdjustment(...)])` の `month_offset` は 1-based（テストと実装で一致）

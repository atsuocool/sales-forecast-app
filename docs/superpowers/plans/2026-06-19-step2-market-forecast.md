# Step 2: 疾患領域・成分市場予測エンジン Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** IQVIAデータを成分単位に集計し、Holt-Winters指数平滑法で36ヶ月の市場規模を予測。直近12ヶ月ホールドアウトによるバックテスト（MAPE/RMSE）で精度確認する。

**Architecture:** `aggregate_market()` でDBから成分×月次の合計市場量を取得し、`MarketForecaster` クラスがstatsmodelsのExponentialSmoothingでフィット→予測する。バックテストは最後の12ヶ月をhold-outとして精度を計算する。全ロジックはPythonのみで完結（FastAPIは後のステップ）。

**Tech Stack:** Python 3.9, statsmodels>=0.14, numpy, pandas, sqlite3, pytest

## Global Constraints

- Python 3.9.6: `X | Y` union構文は使用不可。`Optional[X]`/`Union[X,Y]` を使う
- 全金額はJPY内部保持（仕様書6.3節）
- DBファイル: `data/pharma_forecast.db`
- サンプルデータ: `docs/sample_data/`
- ingredient_id は `ING01`〜`ING04` の4成分（既にStep 1でロード済み）
- 訓練/テスト分割: 2023-01〜2025-05（29ヶ月）/ 2025-06〜2026-05（12ヶ月）
- 季節モデル適用条件: 訓練データが24ヶ月以上の場合のみ（seasonal_periods=12）

---

## File Structure

```
src/
  forecast/
    __init__.py          # 空
    metrics.py           # mape(), rmse() — 精度指標のみ
    market_forecast.py   # aggregate_market(), MarketForecaster, backtest()
tests/
  test_market_forecast.py
scripts/
  run_forecast.py        # デモ: 全4成分のバックテスト＋36ヶ月予測を表示
requirements.txt         # statsmodels>=0.14 を追加
```

---

### Task 1: statsmodels 追加 + 精度指標モジュール

**Files:**
- Modify: `requirements.txt`
- Create: `src/forecast/__init__.py`
- Create: `src/forecast/metrics.py`
- Create: `tests/test_market_forecast.py`（metrics テストのみ）

**Interfaces:**
- Produces:
  - `mape(actual: np.ndarray, predicted: np.ndarray) -> float` — 百分率で返す（例: 5.2%なら5.2）
  - `rmse(actual: np.ndarray, predicted: np.ndarray) -> float`

- [ ] **Step 1: テストを書く**

`tests/test_market_forecast.py` に以下を追記（ファイル新規作成）:
```python
import numpy as np
import pytest
from src.forecast.metrics import mape, rmse


def test_mape_exact():
    actual    = np.array([100.0, 200.0, 50.0])
    predicted = np.array([110.0, 180.0, 55.0])
    expected  = (10/100 + 20/200 + 5/50) / 3 * 100
    assert abs(mape(actual, predicted) - expected) < 1e-6


def test_mape_ignores_zero_actual():
    actual    = np.array([0.0, 100.0])
    predicted = np.array([99.0, 110.0])
    # ゼロ除算を無視し非ゼロ要素のみで計算 → 10%
    assert abs(mape(actual, predicted) - 10.0) < 1e-6


def test_rmse_exact():
    actual    = np.array([1.0, 2.0, 3.0])
    predicted = np.array([1.0, 2.0, 4.0])
    assert abs(rmse(actual, predicted) - np.sqrt(1/3)) < 1e-6
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd ~/projects/sales-forecast-app
python3 -m pytest tests/test_market_forecast.py -v
```

Expected: FAIL - "cannot import name 'mape'"

- [ ] **Step 3: statsmodels を requirements.txt に追加**

`requirements.txt`:
```
pandas>=2.0
openpyxl>=3.1
pytest>=8.0
numpy>=1.26
statsmodels>=0.14
```

```bash
pip3 install statsmodels -q
```

- [ ] **Step 4: モジュールを実装**

`src/forecast/__init__.py`: （空ファイル）

`src/forecast/metrics.py`:
```python
import numpy as np


def mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Percentage Error (%). ゼロの実績値は除外して計算。"""
    actual    = np.asarray(actual,    dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = actual != 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100)


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Root Mean Squared Error."""
    actual    = np.asarray(actual,    dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))
```

- [ ] **Step 5: テストが通ることを確認**

```bash
python3 -m pytest tests/test_market_forecast.py -v
```

Expected: PASSED (3 tests)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/forecast/ tests/test_market_forecast.py
git commit -m "feat: accuracy metrics module (mape, rmse) for Step 2"
```

---

### Task 2: `aggregate_market()` — DB集計関数

**Files:**
- Create: `src/forecast/market_forecast.py`（`aggregate_market` のみ）
- Modify: `tests/test_market_forecast.py`（テスト追加）

**Interfaces:**
- Consumes: `market_data` テーブル（Step 1でロード済み）
- Produces:
  - `aggregate_market(conn: sqlite3.Connection, ingredient_id: str) -> pd.DataFrame`
    - columns: `period`(str), `total_units`(float), `total_amount_jpy`(float), `penetration_rate`(float)
    - 行数 = その成分の月数（ING01〜ING04 で各41行）
    - period 昇順ソート済み

- [ ] **Step 1: テストを書く**

`tests/test_market_forecast.py` に追記:
```python
import sqlite3
import pytest
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.forecast.market_forecast import aggregate_market

DATA_DIR = "docs/sample_data"
IQVIA_CSV = "docs/sample_data/iqvia_market_data.csv"
ING_ID    = "ING01"


@pytest.fixture
def market_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    load_iqvia(mem_conn, IQVIA_CSV)
    return mem_conn


def test_aggregate_market_shape(market_conn):
    df = aggregate_market(market_conn, ING_ID)
    assert len(df) == 41  # 2023-01 to 2026-05
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
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
python3 -m pytest tests/test_market_forecast.py::test_aggregate_market_shape -v
```

Expected: FAIL - "cannot import name 'aggregate_market'"

- [ ] **Step 3: `aggregate_market` を実装**

`src/forecast/market_forecast.py` を新規作成:
```python
import sqlite3
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, List
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.forecast.metrics import mape, rmse


def aggregate_market(conn: sqlite3.Connection, ingredient_id: str) -> pd.DataFrame:
    """
    market_data テーブルから全メーカー区分を合算し、成分×月次の総市場量を返す。
    戻り値: period(str), total_units(float), total_amount_jpy(float), penetration_rate(float)
    """
    return pd.read_sql(
        """
        SELECT period,
               SUM(sales_units)                       AS total_units,
               SUM(sales_amount_jpy)                  AS total_amount_jpy,
               MAX(generic_biosimilar_penetration_rate) AS penetration_rate
        FROM market_data
        WHERE ingredient_id = ?
        GROUP BY period
        ORDER BY period
        """,
        conn,
        params=[ingredient_id],
    )
```

- [ ] **Step 4: テストが通ることを確認**

```bash
python3 -m pytest tests/test_market_forecast.py -k "aggregate" -v
```

Expected: PASSED (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/forecast/market_forecast.py tests/test_market_forecast.py
git commit -m "feat: aggregate_market() - sum all manufacturers per ingredient/period"
```

---

### Task 3: `MarketForecaster` — フィット + 予測 + 信頼区間

**Files:**
- Modify: `src/forecast/market_forecast.py`（クラス追加）
- Modify: `tests/test_market_forecast.py`（テスト追加）

**Interfaces:**
- Consumes: `aggregate_market()` の戻り値 DataFrame
- Produces:
  - `MarketForecaster(ingredient_id: str, horizon: int = 36)`
  - `.fit(df: pd.DataFrame) -> MarketForecaster` — df は aggregate_market の出力
  - `.predict() -> ForecastResult`
  - `ForecastResult.ingredient_id: str`
  - `ForecastResult.periods: List[str]` — YYYY-MM の horizon 個のリスト
  - `ForecastResult.forecast_units: np.ndarray`
  - `ForecastResult.forecast_amount_jpy: np.ndarray`
  - `ForecastResult.lower_units: np.ndarray` — 80%下限
  - `ForecastResult.upper_units: np.ndarray` — 80%上限

- [ ] **Step 1: テストを書く**

`tests/test_market_forecast.py` に追記:
```python
from src.forecast.market_forecast import MarketForecaster, ForecastResult


def test_forecaster_predict_shape(market_conn):
    df     = aggregate_market(market_conn, ING_ID)
    result = MarketForecaster(ING_ID, horizon=36).fit(df).predict()
    assert isinstance(result, ForecastResult)
    assert len(result.periods) == 36
    assert result.forecast_units.shape       == (36,)
    assert result.forecast_amount_jpy.shape  == (36,)
    assert result.lower_units.shape          == (36,)
    assert result.upper_units.shape          == (36,)


def test_forecaster_periods_sequential(market_conn):
    df     = aggregate_market(market_conn, ING_ID)
    result = MarketForecaster(ING_ID, horizon=3).fit(df).predict()
    # 最終訓練月 2026-05 の翌月から始まる
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


def test_forecaster_fit_required(market_conn):
    with pytest.raises(RuntimeError, match="fit"):
        MarketForecaster(ING_ID).predict()
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
python3 -m pytest tests/test_market_forecast.py -k "forecaster" -v
```

Expected: FAIL - "cannot import name 'MarketForecaster'"

- [ ] **Step 3: `ForecastResult` と `MarketForecaster` を実装**

`src/forecast/market_forecast.py` に追記（`aggregate_market` の後に追加）:
```python
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
    訓練データが24ヶ月以上なら seasonal='add'(seasonal_periods=12)、
    未満なら trend='add' のみ（季節なし）にフォールバック。
    """
    MIN_SEASONAL_MONTHS = 24
    SEASONAL_PERIODS    = 12

    def __init__(self, ingredient_id: str, horizon: int = 36):
        self.ingredient_id = ingredient_id
        self.horizon       = horizon
        self._fit_units    = None
        self._fit_amount   = None
        self._last_period  = None
        self._std_units    = None
        self._std_amount   = None

    def fit(self, df: pd.DataFrame) -> "MarketForecaster":
        """
        df: aggregate_market() の出力。period 昇順ソート済みであること。
        """
        use_seasonal = len(df) >= self.MIN_SEASONAL_MONTHS

        def _fit(series: pd.Series):
            kwargs = dict(
                trend="add",
                initialization_method="estimated",
            )
            if use_seasonal:
                kwargs["seasonal"]         = "add"
                kwargs["seasonal_periods"] = self.SEASONAL_PERIODS
            return ExponentialSmoothing(series, **kwargs).fit(optimized=True, disp=False)

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
        """fit() 後に呼ぶ。horizon ステップ先の点予測 + 80%予測区間を返す。"""
        if self._fit_units is None:
            raise RuntimeError("predict() の前に fit() を呼んでください")

        fc_units  = self._fit_units.forecast(self.horizon).values
        fc_amount = self._fit_amount.forecast(self.horizon).values

        # 80% 予測区間: ±1.28σ√h（残差標準偏差の累積誤差近似）
        h      = np.arange(1, self.horizon + 1)
        margin_units  = 1.28 * self._std_units  * np.sqrt(h)
        margin_amount = 1.28 * self._std_amount * np.sqrt(h)

        return ForecastResult(
            ingredient_id       = self.ingredient_id,
            periods             = self._next_periods(),
            forecast_units      = np.maximum(fc_units,              0),
            forecast_amount_jpy = np.maximum(fc_amount,             0),
            lower_units         = np.maximum(fc_units - margin_units,  0),
            upper_units         = np.maximum(fc_units + margin_units,  0),
        )
```

- [ ] **Step 4: テストが通ることを確認**

```bash
python3 -m pytest tests/test_market_forecast.py -k "forecaster" -v
```

Expected: PASSED (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/forecast/market_forecast.py tests/test_market_forecast.py
git commit -m "feat: MarketForecaster - Holt-Winters fit/predict with 80% prediction interval"
```

---

### Task 4: `backtest()` — ホールドアウト精度検証

**Files:**
- Modify: `src/forecast/market_forecast.py`（`backtest` 関数追加）
- Modify: `tests/test_market_forecast.py`（テスト追加）

**Interfaces:**
- Consumes: `aggregate_market()`, `MarketForecaster`
- Produces:
  - `backtest(conn, ingredient_id, test_periods=12, horizon=36) -> BacktestResult`
  - `BacktestResult.train_periods: int`
  - `BacktestResult.test_periods: int`
  - `BacktestResult.mape_units: float`
  - `BacktestResult.rmse_units: float`
  - `BacktestResult.mape_amount: float`
  - `BacktestResult.rmse_amount: float`
  - `BacktestResult.actual: pd.DataFrame` — columns: period, total_units, total_amount_jpy
  - `BacktestResult.predicted: pd.DataFrame` — columns: period, forecast_units, forecast_amount_jpy

- [ ] **Step 1: テストを書く**

`tests/test_market_forecast.py` に追記:
```python
from src.forecast.market_forecast import backtest, BacktestResult


def test_backtest_split(market_conn):
    result = backtest(market_conn, ING_ID, test_periods=12)
    assert result.train_periods == 29  # 41 - 12
    assert result.test_periods  == 12


def test_backtest_mape_reasonable(market_conn):
    result = backtest(market_conn, ING_ID, test_periods=12)
    assert result.mape_units   < 50.0  # 50%未満なら最低限合格
    assert result.rmse_units   > 0.0
    assert result.mape_amount  < 50.0


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
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
python3 -m pytest tests/test_market_forecast.py -k "backtest" -v
```

Expected: FAIL - "cannot import name 'backtest'"

- [ ] **Step 3: `BacktestResult` と `backtest()` を実装**

`src/forecast/market_forecast.py` に追記（`MarketForecaster` クラスの後）:
```python
@dataclass
class BacktestResult:
    ingredient_id: str
    train_periods: int
    test_periods:  int
    mape_units:    float
    rmse_units:    float
    mape_amount:   float
    rmse_amount:   float
    actual:        pd.DataFrame  # period, total_units, total_amount_jpy
    predicted:     pd.DataFrame  # period, forecast_units, forecast_amount_jpy


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

    forecaster = MarketForecaster(ingredient_id, horizon=test_periods)
    forecaster.fit(df_train)
    fc = forecaster.predict()

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
            "period":               fc.periods[:test_periods],
            "forecast_units":       fc.forecast_units,
            "forecast_amount_jpy":  fc.forecast_amount_jpy,
        }),
    )
```

- [ ] **Step 4: テストが通ることを確認**

```bash
python3 -m pytest tests/test_market_forecast.py -k "backtest" -v
```

Expected: PASSED (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/forecast/market_forecast.py tests/test_market_forecast.py
git commit -m "feat: backtest() - 12-month hold-out accuracy evaluation (MAPE/RMSE)"
```

---

### Task 5: デモスクリプト + 全テスト確認

**Files:**
- Create: `scripts/run_forecast.py`

- [ ] **Step 1: 全テストを実行**

```bash
cd ~/projects/sales-forecast-app
python3 -m pytest tests/ -v
```

Expected: 全テスト PASSED（既存19件 + 新規16件 = 35件）

- [ ] **Step 2: デモスクリプトを作成**

`scripts/run_forecast.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import get_connection
from src.forecast.market_forecast import aggregate_market, MarketForecaster, backtest

DB_PATH = "data/pharma_forecast.db"


def main():
    conn = get_connection(DB_PATH)
    ingredients = conn.execute(
        "SELECT ingredient_id, name FROM ingredients ORDER BY ingredient_id"
    ).fetchall()

    print("=" * 65)
    print("バックテスト結果（直近12ヶ月ホールドアウト）")
    print("=" * 65)
    for row in ingredients:
        ing_id, name = row["ingredient_id"], row["name"]
        result = backtest(conn, ing_id, test_periods=12)
        print(f"\n{name} ({ing_id})")
        print(f"  訓練: {result.train_periods}ヶ月 / テスト: {result.test_periods}ヶ月")
        print(f"  MAPE(数量): {result.mape_units:5.1f}%   RMSE(数量): {result.rmse_units:>12,.0f}")
        print(f"  MAPE(金額): {result.mape_amount:5.1f}%   RMSE(金額): {result.rmse_amount:>12,.0f}円")

    print("\n" + "=" * 65)
    print("36ヶ月フォーキャスト（2026-06〜2029-05）")
    print("=" * 65)
    for row in ingredients:
        ing_id, name = row["ingredient_id"], row["name"]
        df     = aggregate_market(conn, ing_id)
        result = MarketForecaster(ing_id, horizon=36).fit(df).predict()
        y1 = result.forecast_units[:12].sum()
        y2 = result.forecast_units[12:24].sum()
        y3 = result.forecast_units[24:36].sum()
        print(f"\n{name}")
        print(f"  1年目 ({result.periods[0]}〜{result.periods[11]}): {y1:>12,.0f} 単位")
        print(f"  2年目 ({result.periods[12]}〜{result.periods[23]}): {y2:>12,.0f} 単位")
        print(f"  3年目 ({result.periods[24]}〜{result.periods[35]}): {y3:>12,.0f} 単位")

    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: デモスクリプトを実行して出力を確認**

```bash
python3 scripts/run_forecast.py
```

Expected output（数値は例）:
```
=================================================================
バックテスト結果（直近12ヶ月ホールドアウト）
=================================================================

メトホルミン塩酸塩 (ING01)
  訓練: 29ヶ月 / テスト: 12ヶ月
  MAPE(数量):   X.X%   RMSE(数量):      XXXXXX
  MAPE(金額):   X.X%   RMSE(金額):      XXXXXX円
...

=================================================================
36ヶ月フォーキャスト（2026-06〜2029-05）
=================================================================

メトホルミン塩酸塩
  1年目 (2026-06〜2027-05):    XXXXXXX 単位
  2年目 (2027-06〜2028-05):    XXXXXXX 単位
  3年目 (2028-06〜2029-05):    XXXXXXX 単位
...
```

- [ ] **Step 4: 最終 commit**

```bash
git add scripts/run_forecast.py requirements.txt
git commit -m "feat: Step 2 complete - market forecast engine with Holt-Winters + backtest"
```

---

## Self-Review

**Spec coverage (仕様書6.1 Step1 / 13章 Step2):**
- [x] IQVIAデータを成分単位で集計 → `aggregate_market()`
- [x] 時系列モデルで将来トレンドを予測 → `MarketForecaster`（Holt-Winters 線形トレンド＋季節性）
- [x] 単一成分でのプロトタイプ → ING01 を主テスト対象
- [x] バックテスト（直近12ヶ月ホールドアウト） → `backtest()`
- [x] MAPE / RMSE で精度評価 → `metrics.py`
- [x] 4成分すべてに適用可能 → `test_backtest_all_ingredients`
- [x] 信頼区間（80%）→ `lower_units` / `upper_units`（仕様書5.1節）
- [x] 将来36ヶ月予測 → `horizon=36`（デフォルト）

**Placeholder scan:** なし。全ステップにコードあり。

**Type consistency:**
- `aggregate_market` → `pd.DataFrame` with `total_units`, `total_amount_jpy`, `penetration_rate`
- `MarketForecaster.fit(df)` で参照するカラム名が上記と一致
- `ForecastResult.periods: List[str]` → `backtest()` で `fc.periods[:test_periods]` を使用し一致
- `BacktestResult.actual` のカラム名 `["period", "total_units", "total_amount_jpy"]` → テストと一致

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from src.forecast.market_forecast import aggregate_market, MarketForecaster
from src.forecast.penetration import PenetrationForecaster, EventAdjustment
from src.forecast.own_share import aggregate_own_share, OwnShareForecaster
from src.forecast.sku_mix import aggregate_sellout_by_sku, SkuMixForecaster


@dataclass
class SkuForecastResult:
    sku_id:            str
    product_id:        str
    ingredient_id:     str
    periods:           List[str]             # YYYY-MM, horizon 個
    sellout_units:     np.ndarray            # shape: (horizon,)
    sellout_amount_jpy: np.ndarray           # shape: (horizon,)


def _avg_unit_price(conn: sqlite3.Connection, sku_id: str) -> float:
    """sellout_data の全期間実績から SKU の平均単価（JPY/unit）を返す。"""
    row = conn.execute(
        "SELECT SUM(amount_jpy), SUM(quantity) FROM sellout_data WHERE sku_id = ?",
        (sku_id,),
    ).fetchone()
    total_amount, total_qty = row[0] or 0.0, row[1] or 0.0
    return total_amount / total_qty if total_qty > 0 else 0.0


def _product_id_for_ingredient(conn: sqlite3.Connection, ingredient_id: str) -> str:
    row = conn.execute(
        "SELECT product_id FROM products WHERE ingredient_id = ? LIMIT 1",
        (ingredient_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"ingredient_id '{ingredient_id}' に対応する製品が見つかりません")
    return row[0]


def run_integrated_forecast(
    conn:               sqlite3.Connection,
    ingredient_id:      str,
    horizon:            int = 36,
    penetration_events: Optional[List[EventAdjustment]] = None,
) -> List[SkuForecastResult]:
    """
    Step 1〜4 を統合した SKU 単位の 36 ヶ月予測を実行する。

    パイプライン:
      1. 市場総量予測（Holt-Winters） → forecast_units[t]
      2. 浸透率予測（ロジスティック） → penetration[t]
      3. 自社シェア予測（線形トレンド）→ own_share[t]
      4. GE/BS 自社数量 = forecast_units × penetration × own_share
      5. SKU 構成比予測（線形トレンド＋正規化）→ mix_ratio[t, sku]
      6. SKU 数量 = GE/BS 自社数量 × mix_ratio
      7. SKU 金額 = SKU 数量 × 平均単価

    Parameters
    ----------
    penetration_events : 制度変更イベントリスト（PenetrationForecaster.predict() に渡す）
    """
    # ---- Step 1: 市場総量予測 ----
    market_df = aggregate_market(conn, ingredient_id)
    market_fc = MarketForecaster(ingredient_id, horizon=horizon).fit(market_df).predict()
    periods   = market_fc.periods                            # List[str], len=horizon

    # ---- Step 2: 浸透率予測 ----
    pen_fc = (
        PenetrationForecaster(ingredient_id)
        .fit(market_df)
        .predict(horizon=horizon, events=penetration_events)
    )   # np.ndarray shape (horizon,)

    # ---- Step 3: 自社シェア予測 ----
    own_df     = aggregate_own_share(conn, ingredient_id)
    own_share  = OwnShareForecaster(ingredient_id).fit(own_df).predict(horizon)

    # ---- Step 4: GE/BS 自社数量 ----
    ge_bs_own_units = market_fc.forecast_units * pen_fc * own_share

    # ---- Step 5–7: SKU 配分 ----
    product_id   = _product_id_for_ingredient(conn, ingredient_id)
    sellout_df   = aggregate_sellout_by_sku(conn, product_id)
    mix_forecast = SkuMixForecaster(product_id).fit(sellout_df).predict(horizon)

    sku_ids = sorted(mix_forecast["sku_id"].unique())
    results: List[SkuForecastResult] = []

    for sku_id in sku_ids:
        sku_mix = (
            mix_forecast[mix_forecast["sku_id"] == sku_id]
            .sort_values("month_offset")["forecast_mix_ratio"]
            .values
        )   # shape (horizon,)

        sku_units  = ge_bs_own_units * sku_mix
        avg_price  = _avg_unit_price(conn, sku_id)
        sku_amount = sku_units * avg_price

        results.append(SkuForecastResult(
            sku_id             = sku_id,
            product_id         = product_id,
            ingredient_id      = ingredient_id,
            periods            = periods,
            sellout_units      = sku_units,
            sellout_amount_jpy = sku_amount,
        ))

    return results

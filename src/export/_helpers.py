"""共通ヘルパー: 定数・データ取得関数"""
import numpy as np
import pandas as pd

HORIZON = 36
INGREDIENTS = {
    "ING01": "メトホルミン塩酸塩",
    "ING02": "アトルバスタチン",
    "ING03": "フィルグラスチム",
    "ING04": "インフリキシマブ",
}
BRAND_BLUE  = "#2563EB"
BRAND_RED   = "#DC2626"
BRAND_GREEN = "#16A34A"
BRAND_GRAY  = "#94A3B8"


def next_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return f"{y:04d}-{m:02d}"


def load_sku_fc_df(conn, ing_id: str, axis1: str, axis2: str, horizon: int = HORIZON) -> pd.DataFrame:
    from src.forecast.market_forecast import aggregate_market
    from src.forecast.scenario import build_penetration_events
    from src.forecast.integrated_forecast import run_integrated_forecast

    df_m = aggregate_market(conn, ing_id)
    start = next_period(df_m["period"].iloc[-1])
    events = build_penetration_events(conn, start, horizon, axis1, axis2)
    results = run_integrated_forecast(conn, ing_id, horizon=horizon, penetration_events=events)

    rows = []
    for r in results:
        for period, units, amt in zip(r.periods, r.sellout_units, r.sellout_amount_jpy):
            rows.append({"period": period, "sku_id": r.sku_id, "units": units, "amount_jpy": float(amt)})
    return pd.DataFrame(rows)


def get_actual_sellout_12m(conn, ing_id: str) -> float:
    """直近12ヶ月の自社 Sell-out 合計（JPY）"""
    rows = conn.execute("""
        SELECT sd.period, SUM(sd.amount_jpy) AS amt
        FROM sellout_data sd
        JOIN skus s ON sd.sku_id = s.sku_id
        JOIN products p ON s.product_id = p.product_id
        WHERE p.ingredient_id = ?
        GROUP BY sd.period
        ORDER BY sd.period DESC
        LIMIT 12
    """, (ing_id,)).fetchall()
    return float(sum(r["amt"] or 0 for r in rows))

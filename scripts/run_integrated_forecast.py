"""
Step 4 統合予測スクリプト
市場総量 × 浸透率 × 自社シェア × SKU 構成比 → SKU 単位 36 ヶ月予測
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from src.db.connection import get_connection
from src.forecast.penetration import EventAdjustment
from src.forecast.integrated_forecast import run_integrated_forecast

DB_PATH = "data/pharma_forecast.db"
HORIZON = 36

TARGETS = [
    ("ING01", "メトホルミン塩酸塩",         None),
    ("ING02", "アトルバスタチン",           None),
    ("ING03", "フィルグラスチム",           [EventAdjustment(month_offset=11, ceiling_delta=0.05,
                                                              speed_delta=0.01, label="使用促進策")]),
    ("ING04", "インフリキシマブ",           [EventAdjustment(month_offset=11, ceiling_delta=0.05,
                                                              speed_delta=0.01, label="使用促進策")]),
]


def _year_totals(values: np.ndarray, periods: list) -> dict:
    """月次配列を年次合計に変換する。"""
    year_map: dict = {}
    for val, period in zip(values, periods):
        year = period[:4]
        year_map[year] = year_map.get(year, 0.0) + val
    return year_map


def main():
    conn = get_connection(DB_PATH)
    sep  = "=" * 70

    print(sep)
    print("  統合予測（製品→SKU 配分）  36 ヶ月 Sell-out 予測")
    print(sep)

    for ing_id, name, events in TARGETS:
        print(f"\n{'─' * 70}")
        print(f"  {name}（{ing_id}）")
        print(f"{'─' * 70}")

        results = run_integrated_forecast(conn, ing_id, horizon=HORIZON, penetration_events=events)
        periods = results[0].periods

        for r in sorted(results, key=lambda x: x.sku_id):
            year_units  = _year_totals(r.sellout_units,      periods)
            year_amount = _year_totals(r.sellout_amount_jpy, periods)

            print(f"\n  SKU: {r.sku_id}")
            print(f"  {'年度':<8} {'数量(本)':>12} {'金額(万JPY)':>14}")
            print(f"  {'─'*36}")
            for year in sorted(year_units):
                u = year_units[year]
                a = year_amount[year] / 10_000
                print(f"  {year}  {u:>12,.0f}  {a:>14,.1f}")

        all_units  = sum(r.sellout_units      for r in results)
        all_amount = sum(r.sellout_amount_jpy for r in results)
        print(f"\n  ▶ 製品合計（全 SKU）")
        print(f"  {'年度':<8} {'数量(本)':>12} {'金額(万JPY)':>14}")
        print(f"  {'─'*36}")
        for year, u in sorted(_year_totals(all_units, periods).items()):
            a = _year_totals(all_amount, periods)[year] / 10_000
            print(f"  {year}  {u:>12,.0f}  {a:>14,.1f}")

    conn.close()
    print(f"\n{sep}")
    print("  完了")
    print(sep)


if __name__ == "__main__":
    main()

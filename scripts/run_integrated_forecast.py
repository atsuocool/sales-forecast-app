"""
統合予測スクリプト（Step 4 + Step 5 + Step 6）
市場総量 × 浸透率 × 自社シェア × SKU 構成比 → SKU 単位 36 ヶ月予測
制度変更シナリオ（adjusted/excluded）+ 通貨切替（JPY/USD）対応
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import numpy as np

from src.db.connection import get_connection
from src.forecast.market_forecast import aggregate_market
from src.forecast.integrated_forecast import run_integrated_forecast
from src.forecast.scenario import build_penetration_events
from src.forecast.currency import get_forecast_rate, convert_amounts, format_amount

DB_PATH = "data/pharma_forecast.db"
HORIZON = 36

TARGETS = [
    ("ING01", "メトホルミン塩酸塩"),
    ("ING02", "アトルバスタチン"),
    ("ING03", "フィルグラスチム"),
    ("ING04", "インフリキシマブ"),
]


def _year_totals(values: np.ndarray, periods: list) -> dict:
    year_map: dict = {}
    for val, period in zip(values, periods):
        year = period[:4]
        year_map[year] = year_map.get(year, 0.0) + val
    return year_map


def _next_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return f"{y:04d}-{m:02d}"


def main():
    parser = argparse.ArgumentParser(description="統合 SKU 予測")
    parser.add_argument("--currency", choices=["JPY", "USD"], default="JPY")
    parser.add_argument("--scenario", choices=["regulatory_adjusted", "regulatory_excluded"],
                        default="regulatory_adjusted")
    parser.add_argument("--axis2", choices=["base", "optimistic", "pessimistic"], default="base")
    parser.add_argument("--rate", type=float, default=None,
                        help="JPY/USD レート（省略時は DB の forecast_assumption を使用）")
    args = parser.parse_args()

    conn = get_connection(DB_PATH)

    fx_rate = args.rate if args.rate else get_forecast_rate(conn)
    sep = "=" * 72

    print(sep)
    print(f"  統合予測（SKU 36 ヶ月）  シナリオ: {args.scenario} / {args.axis2}")
    print(f"  通貨: {args.currency}  為替レート: ¥{fx_rate:.1f}/USD")
    print(sep)

    for ing_id, name in TARGETS:
        print(f"\n{'─' * 72}")
        print(f"  {name}（{ing_id}）")
        print(f"{'─' * 72}")

        # 予測開始月を算出
        df = aggregate_market(conn, ing_id)
        forecast_start = _next_period(df["period"].iloc[-1])

        # シナリオに応じた浸透率イベント
        pen_events = build_penetration_events(
            conn, forecast_start, HORIZON,
            scenario_axis1=args.scenario,
            scenario_axis2=args.axis2,
        )

        results = run_integrated_forecast(
            conn, ing_id, horizon=HORIZON, penetration_events=pen_events
        )
        periods = results[0].periods

        unit_label   = "万JPY" if args.currency == "JPY" else "万USD"
        unit_divisor = 10_000

        for r in sorted(results, key=lambda x: x.sku_id):
            amounts_display = convert_amounts(r.sellout_amount_jpy, args.currency, fx_rate)
            year_units  = _year_totals(r.sellout_units,    periods)
            year_amount = _year_totals(amounts_display,    periods)

            print(f"\n  SKU: {r.sku_id}")
            print(f"  {'年度':<8} {'数量(本)':>12} {f'金額({unit_label})':>14}")
            print(f"  {'─' * 38}")
            for year in sorted(year_units):
                u = year_units[year]
                a = year_amount[year] / unit_divisor
                print(f"  {year}  {u:>12,.0f}  {a:>14,.1f}")

        # 製品合計
        all_units   = sum(r.sellout_units for r in results)
        all_amounts = convert_amounts(
            sum(r.sellout_amount_jpy for r in results), args.currency, fx_rate
        )
        print(f"\n  ▶ 製品合計（全 SKU）")
        print(f"  {'年度':<8} {'数量(本)':>12} {f'金額({unit_label})':>14}")
        print(f"  {'─' * 38}")
        for year, u in sorted(_year_totals(all_units, periods).items()):
            a = _year_totals(all_amounts, periods)[year] / unit_divisor
            print(f"  {year}  {u:>12,.0f}  {a:>14,.1f}")

    conn.close()
    print(f"\n{sep}")
    print("  完了")
    print(sep)


if __name__ == "__main__":
    main()

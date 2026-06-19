"""
ING03（フィルグラスチム）浸透率カーブ シナリオ比較プロット

regulatory_adjusted（3ヶ月漸増ランプ）vs regulatory_excluded（変化なし）を重ね描きし、
2026-06 制度変更以降の緩やかな乖離を確認する。
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import numpy as np

matplotlib.rcParams["font.family"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]

from src.db.connection import get_connection
from src.forecast.market_forecast import aggregate_market
from src.forecast.penetration import PenetrationForecaster
from src.forecast.scenario import build_penetration_events

DB_PATH    = "data/pharma_forecast.db"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

ING_ID  = "ING03"
NAME    = "フィルグラスチム"
HORIZON = 36


def _period_to_date(p: str) -> datetime:
    return datetime.strptime(p + "-01", "%Y-%m-%d")


def _next_periods(last: str, n: int):
    y, m = int(last[:4]), int(last[5:7])
    out = []
    for _ in range(n):
        m += 1
        if m > 12:
            m, y = 1, y + 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def main():
    conn = get_connection(DB_PATH)
    df   = aggregate_market(conn, ING_ID)

    last_actual     = df["period"].iloc[-1]
    forecast_start  = _next_periods(last_actual, 1)[0]   # 2026-06
    fc_periods      = _next_periods(last_actual, HORIZON)
    fc_dates        = [_period_to_date(p) for p in fc_periods]
    actual_dates    = [_period_to_date(p) for p in df["period"]]

    forecaster = PenetrationForecaster(ING_ID).fit(df)
    fit_r      = forecaster.get_fit_result()

    # --- シナリオ別予測 ---
    scenarios = {
        "base":        ("regulatory_adjusted", "base",        "#DC2626", "-",  2.2),  # 赤
        "optimistic":  ("regulatory_adjusted", "optimistic",  "#EA580C", "--", 1.4),  # オレンジ
        "pessimistic": ("regulatory_adjusted", "pessimistic", "#F97316", ":",  1.2),  # 薄オレンジ
        "excluded":    ("regulatory_excluded",  "base",        "#2563EB", "-",  2.2),  # 青
    }

    forecasts = {}
    for key, (ax1, ax2, *_) in scenarios.items():
        events = build_penetration_events(
            conn, forecast_start, HORIZON,
            scenario_axis1=ax1, scenario_axis2=ax2,
        )
        forecasts[key] = forecaster.predict(horizon=HORIZON, events=events)

    conn.close()

    # ---- プロット ----
    fig, ax = plt.subplots(figsize=(14, 6))

    # 実績
    ax.plot(actual_dates, df["penetration_rate"],
            "o", color="#1E3A5F", markersize=4, zorder=6, label="実績")

    # フィット曲線（実績期間のみ）
    ax.plot(actual_dates, fit_r.fitted,
            "--", color="#64748B", linewidth=1.2, alpha=0.7,
            label=f"フィット曲線（R²={fit_r.r_squared:.3f}）")

    # --- regulatory_excluded（制度変更なし）---
    ax.plot(fc_dates, forecasts["excluded"],
            "-", color="#2563EB", linewidth=2.5,
            label="予測：非加味シナリオ（regulatory_excluded）", zorder=5)

    # --- regulatory_adjusted × 3軸2 ---
    ax.plot(fc_dates, forecasts["base"],
            "-", color="#DC2626", linewidth=2.5,
            label="予測：加味 ベース（+5pp / +0.02）", zorder=5)
    ax.plot(fc_dates, forecasts["optimistic"],
            "--", color="#EA580C", linewidth=1.6,
            label="予測：加味 楽観（仮値×1.5）")
    ax.plot(fc_dates, forecasts["pessimistic"],
            ":", color="#F97316", linewidth=1.6,
            label="予測：加味 悲観（仮値×0.1）")

    # 乖離の塗りつぶし（base adjusted vs excluded）
    adj_arr = np.array(forecasts["base"])
    exc_arr = np.array(forecasts["excluded"])
    ax.fill_between(fc_dates, exc_arr, adj_arr,
                    where=adj_arr > exc_arr,
                    color="#DC2626", alpha=0.10, label="制度変更による上乗せ幅（base）")

    # 制度変更イベント開始ライン（2026-06）
    event_date = _period_to_date(forecast_start)
    ax.axvline(event_date, color="#7C3AED", linestyle=":", linewidth=1.4, alpha=0.7)
    ax.text(event_date, 0.03,
            "  2026-06\n  使用促進策強化\n  （効果は3ヶ月で漸増）",
            color="#7C3AED", fontsize=8, va="bottom", ha="left",
            transform=ax.get_xaxis_transform())

    # 予測開始境界線
    boundary = _period_to_date(last_actual)
    ax.axvline(boundary, color="#94A3B8", linestyle=":", linewidth=1.0, alpha=0.6)
    ax.text(boundary, 1.01, "  予測開始",
            color="#94A3B8", fontsize=7, ha="left", va="bottom",
            transform=ax.get_xaxis_transform())

    # ランプ期間ハイライト（2026-06 〜 2026-08）
    ramp_end = _period_to_date(_next_periods(forecast_start, 3)[-1])
    ax.axvspan(event_date, ramp_end, color="#7C3AED", alpha=0.05)

    p = fit_r.params
    ax.set_title(
        f"{NAME}（{ING_ID}）浸透率 — シナリオ比較\n"
        f"フィット: L={p.L:.3f}, k={p.k:.4f}, t₀={p.t0:.1f}ヶ月目（R²={fit_r.r_squared:.3f}）",
        fontsize=11,
    )
    ax.set_xlabel("月")
    ax.set_ylabel("浸透率（GE/BS シェア）")
    ax.set_ylim(0, 0.80)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.xticks(rotation=40, ha="right", fontsize=8)
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.9)
    ax.grid(True, alpha=0.25)
    plt.tight_layout()

    out = OUTPUT_DIR / f"scenario_comparison_{ING_ID}.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"保存: {out}")

    # --- 数値確認（乖離の広がり） ---
    print(f"\n{'月':>8}  {'非加味':>8}  {'加味(base)':>10}  {'乖離':>8}  {'楽観':>8}  {'悲観':>8}")
    print("-" * 58)
    for i in [0, 1, 2, 3, 5, 11, 23, 35]:
        if i < HORIZON:
            ex = forecasts["excluded"][i]
            ba = forecasts["base"][i]
            op = forecasts["optimistic"][i]
            pe = forecasts["pessimistic"][i]
            print(f"{fc_periods[i]:>8}  {ex:>7.1%}  {ba:>9.1%}  {ba-ex:>+8.1%}  {op:>7.1%}  {pe:>7.1%}")


if __name__ == "__main__":
    main()

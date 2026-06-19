import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
matplotlib.rcParams["font.family"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
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


def plot_ingredient(conn, ing_id: str, name: str, events=None, horizon: int = 36) -> None:
    df         = aggregate_market(conn, ing_id)
    forecaster = PenetrationForecaster(ing_id).fit(df)
    fit_r      = forecaster.get_fit_result()

    base_fc    = forecaster.predict(horizon=horizon)
    adj_fc     = forecaster.predict(horizon=horizon, events=events) if events else None

    actual_dates = [_period_to_date(p) for p in df["period"]]
    fc_periods   = _next_periods(df["period"].iloc[-1], horizon)
    fc_dates     = [_period_to_date(p) for p in fc_periods]

    fig, ax = plt.subplots(figsize=(13, 5))

    # 実績
    ax.plot(actual_dates, df["penetration_rate"],
            "o-", color="#2563EB", linewidth=1.5, markersize=4,
            label="実績", zorder=5)

    # フィット曲線
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
                    ax.text(ev_date, 1.01, ev.label or "イベント",
                            color="#9333EA", fontsize=7,
                            ha="center", va="bottom", transform=ax.get_xaxis_transform())

    # 予測開始境界線
    boundary = _period_to_date(df["period"].iloc[-1])
    ax.axvline(boundary, color="gray", linestyle=":", alpha=0.5)
    ax.text(boundary, 0.02, "  予測開始",
            color="gray", fontsize=8, ha="left", va="bottom")

    p        = fit_r.params
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

    # 制度変更加味シナリオ: 2027-04 後発品使用促進策強化（上限+5pp、速度+0.01）
    promotion_events = [
        EventAdjustment(month_offset=11, ceiling_delta=0.05,
                        speed_delta=0.01, label="2027-04\n使用促進策"),
    ]

    targets = [
        ("ING03", "フィルグラスチム",   promotion_events),
        ("ING04", "インフリキシマブ",   promotion_events),
        ("ING01", "メトホルミン塩酸塩", None),
        ("ING02", "アトルバスタチン",   None),
    ]

    print("=" * 62)
    print("浸透率ロジスティックカーブ フィッティング＆36ヶ月予測")
    print("=" * 62)
    for ing_id, name, events in targets:
        df = aggregate_market(conn, ing_id)
        r  = PenetrationForecaster(ing_id).fit(df).get_fit_result()
        p  = r.params
        print(f"\n{name} ({ing_id})")
        print(f"  L  (上限)    = {p.L:.4f}  ({p.L:.1%})")
        print(f"  k  (速度)    = {p.k:.5f}")
        print(f"  t0 (変曲点)  = {p.t0:.1f} ヶ月目  (t=0: {r.start_period})")
        print(f"  R²           = {r.r_squared:.4f}")
        plot_ingredient(conn, ing_id, name, events=events)

    conn.close()
    print("\n完了。output/ フォルダを確認してください。")


if __name__ == "__main__":
    main()

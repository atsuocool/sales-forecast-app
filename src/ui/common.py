"""
Streamlit アプリ共通ユーティリティ
DB 接続・データ取得（キャッシュ付き）・サイドバー・Plotly チャートヘルパー
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from src.db.connection import get_connection
from src.forecast.market_forecast import aggregate_market, MarketForecaster
from src.forecast.penetration import PenetrationForecaster
from src.forecast.scenario import build_penetration_events
from src.forecast.currency import get_forecast_rate, convert_amounts
from src.forecast.integrated_forecast import run_integrated_forecast

DB_PATH = str(ROOT / "data" / "pharma_forecast.db")
HORIZON = 36

INGREDIENTS = {
    "ING01": "メトホルミン塩酸塩",
    "ING02": "アトルバスタチン",
    "ING03": "フィルグラスチム",
    "ING04": "インフリキシマブ",
}

AXIS2_LABELS = {"base": "ベース", "optimistic": "楽観 ▲", "pessimistic": "悲観 ▼"}
PLOTLY_FONT = dict(family="Hiragino Sans, Meiryo, Arial", size=12)


# ---------- DB 接続 ----------

@st.cache_resource
def get_conn():
    return get_connection(DB_PATH)


def db_ok() -> bool:
    try:
        get_conn().execute("SELECT 1 FROM market_data LIMIT 1")
        return True
    except Exception:
        return False


# ---------- ユーティリティ ----------

def _next_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    m += 1
    if m > 12:
        m, y = 1, y + 1
    return f"{y:04d}-{m:02d}"


# ---------- キャッシュ付きデータ取得 ----------

@st.cache_data(ttl=300)
def load_market_df(ing_id: str) -> pd.DataFrame:
    return aggregate_market(get_conn(), ing_id)


@st.cache_data(ttl=300)
def get_default_fx() -> float:
    return get_forecast_rate(get_conn())


@st.cache_data(ttl=300)
def get_market_fc(ing_id: str) -> dict:
    df = load_market_df(ing_id)
    fc = MarketForecaster(ing_id, horizon=HORIZON).fit(df).predict()
    return dict(
        periods=fc.periods,
        units=fc.forecast_units.tolist(),
        amount_jpy=fc.forecast_amount_jpy.tolist(),
        lower=fc.lower_units.tolist(),
        upper=fc.upper_units.tolist(),
    )


@st.cache_data(ttl=300)
def get_pen_fit(ing_id: str) -> dict:
    df = load_market_df(ing_id)
    r = PenetrationForecaster(ing_id).fit(df).get_fit_result()
    return dict(
        L=r.params.L, k=r.params.k, t0=r.params.t0, r2=r.r_squared,
        fitted=r.fitted.tolist(), actual=r.actual.tolist(),
    )


@st.cache_data(ttl=300)
def get_pen_fc(ing_id: str, axis1: str, axis2: str) -> list:
    df = load_market_df(ing_id)
    start = _next_period(df["period"].iloc[-1])
    events = build_penetration_events(get_conn(), start, HORIZON, axis1, axis2)
    return PenetrationForecaster(ing_id).fit(df).predict(HORIZON, events=events).tolist()


@st.cache_data(ttl=300)
def get_sku_fc_df(ing_id: str, axis1: str, axis2: str) -> pd.DataFrame:
    df = load_market_df(ing_id)
    start = _next_period(df["period"].iloc[-1])
    events = build_penetration_events(get_conn(), start, HORIZON, axis1, axis2)
    results = run_integrated_forecast(get_conn(), ing_id, horizon=HORIZON, penetration_events=events)
    rows = []
    for r in results:
        for period, units, amt in zip(r.periods, r.sellout_units, r.sellout_amount_jpy):
            rows.append({"period": period, "sku_id": r.sku_id, "units": units, "amount_jpy": amt})
    return pd.DataFrame(rows)


# ---------- サイドバー ----------

def sidebar_controls(show_axis1: bool = True, key: str = "main") -> dict:
    with st.sidebar:
        st.markdown("## ⚙️ 設定")

        ing_id = st.selectbox(
            "🔬 成分",
            list(INGREDIENTS.keys()),
            format_func=lambda x: f"{INGREDIENTS[x]}（{x}）",
            key=f"{key}_ing",
        )

        st.divider()
        currency = st.radio("💴 通貨", ["JPY", "USD"], horizontal=True, key=f"{key}_cur")
        fx = get_default_fx()
        if currency == "USD":
            fx = st.number_input(
                "JPY/USD レート", value=float(fx), step=1.0,
                min_value=50.0, max_value=300.0, key=f"{key}_fx",
            )

        st.divider()
        if show_axis1:
            axis1 = st.radio(
                "📋 制度変更",
                ["regulatory_adjusted", "regulatory_excluded"],
                format_func=lambda x: "加味（Adjusted）" if "adjusted" in x else "非加味（Organic）",
                key=f"{key}_ax1",
            )
        else:
            axis1 = "regulatory_adjusted"

        axis2 = st.radio(
            "📊 シナリオ幅",
            ["base", "optimistic", "pessimistic"],
            format_func=lambda x: AXIS2_LABELS[x],
            horizontal=True,
            key=f"{key}_ax2",
        )

    return dict(ing_id=ing_id, currency=currency, fx=fx, axis1=axis1, axis2=axis2)


# ---------- Plotly チャートヘルパー ----------

def fig_market_trend(ing_id: str) -> go.Figure:
    """市場全体 販売数量推移（Holt-Winters 予測 + 80% PI）"""
    df = load_market_df(ing_id)
    fc = get_market_fc(ing_id)

    actual_x = df["period"].tolist()
    fc_x = fc["periods"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=actual_x, y=(df["total_units"] / 1000).tolist(),
        mode="lines+markers", name="実績",
        line=dict(color="#2563EB", width=2), marker=dict(size=4),
    ))
    fig.add_trace(go.Scatter(
        x=fc_x + fc_x[::-1],
        y=[v / 1000 for v in fc["upper"]] + [v / 1000 for v in fc["lower"]][::-1],
        fill="toself", fillcolor="rgba(220,38,38,0.10)",
        line=dict(color="rgba(0,0,0,0)"), name="80% 予測区間",
    ))
    fig.add_trace(go.Scatter(
        x=fc_x, y=[v / 1000 for v in fc["units"]],
        mode="lines", name="予測（Holt-Winters）",
        line=dict(color="#DC2626", width=2),
    ))
    fig.add_vline(x=actual_x[-1], line_dash="dot", line_color="#94A3B8", opacity=0.5)
    fig.add_annotation(x=actual_x[-1], y=1.0, yref="paper", xanchor="left",
                       text="  予測開始", showarrow=False, font=dict(color="#94A3B8", size=11))
    fig.update_layout(
        title=f"疾患領域・成分市場 数量推移（{INGREDIENTS[ing_id]}）",
        xaxis_title="月", yaxis_title="販売数量（千本）",
        hovermode="x unified", font=PLOTLY_FONT,
        legend=dict(orientation="h", y=1.08), height=380,
    )
    return fig


def fig_penetration(ing_id: str, axis1: str, axis2: str) -> go.Figure:
    """浸透率カーブ：実績 + フィット + adjusted / excluded 予測"""
    df = load_market_df(ing_id)
    fit = get_pen_fit(ing_id)
    fc_adj = get_pen_fc(ing_id, "regulatory_adjusted", axis2)
    fc_exc = get_pen_fc(ing_id, "regulatory_excluded", axis2)
    fc_x = get_market_fc(ing_id)["periods"]
    actual_x = df["period"].tolist()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=actual_x, y=[v * 100 for v in fit["actual"]],
        mode="markers", name="実績", marker=dict(color="#2563EB", size=5),
    ))
    fig.add_trace(go.Scatter(
        x=actual_x, y=[v * 100 for v in fit["fitted"]],
        mode="lines", name=f"フィット曲線（R²={fit['r2']:.3f}）",
        line=dict(color="#16A34A", width=1.5, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=fc_x, y=[v * 100 for v in fc_exc],
        mode="lines", name="予測：非加味（Organic）",
        line=dict(color="#2563EB", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=fc_x, y=[v * 100 for v in fc_adj],
        mode="lines", name="予測：加味（Adjusted）",
        line=dict(color="#DC2626", width=2),
    ))
    # 乖離帯
    fig.add_trace(go.Scatter(
        x=fc_x + fc_x[::-1],
        y=[v * 100 for v in fc_adj] + [v * 100 for v in fc_exc][::-1],
        fill="toself", fillcolor="rgba(220,38,38,0.08)",
        line=dict(color="rgba(0,0,0,0)"), name="制度変更による上乗せ幅",
    ))
    fig.add_vline(x=actual_x[-1], line_dash="dot", line_color="#94A3B8", opacity=0.5)
    fig.add_annotation(x=actual_x[-1], y=1.0, yref="paper", xanchor="left",
                       text="  予測開始", showarrow=False, font=dict(color="#94A3B8", size=11))
    p = fit
    subtitle = f"L={p['L']:.1%}  k={p['k']:.4f}  t₀={p['t0']:.1f}ヶ月"
    fig.update_layout(
        title=f"GE/BS 浸透率カーブ（{INGREDIENTS[ing_id]}）<br><sub>{subtitle}</sub>",
        xaxis_title="月", yaxis_title="浸透率（%）",
        yaxis=dict(tickformat=".0f", ticksuffix="%"),
        hovermode="x unified", font=PLOTLY_FONT,
        legend=dict(orientation="h", y=1.12), height=380,
    )
    return fig


def fig_sku_forecast(ing_id: str, axis1: str, axis2: str, currency: str, fx: float) -> go.Figure:
    """SKU 別月次 Sell-out 金額予測（積み上げ棒グラフ）"""
    df = get_sku_fc_df(ing_id, axis1, axis2).copy()
    df["amount"] = convert_amounts(df["amount_jpy"].values, currency, fx)
    unit = "万JPY" if currency == "JPY" else "万USD"

    fig = go.Figure()
    sku_colors = ["#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#14B8A6"]
    for i, sku_id in enumerate(sorted(df["sku_id"].unique())):
        sub = df[df["sku_id"] == sku_id].sort_values("period")
        fig.add_trace(go.Bar(
            x=sub["period"], y=sub["amount"] / 10_000,
            name=sku_id, marker_color=sku_colors[i % len(sku_colors)],
        ))
    fig.update_layout(
        barmode="stack",
        title=f"自社 SKU 月次 Sell-out 金額予測（{INGREDIENTS[ing_id]}）",
        xaxis_title="月", yaxis_title=f"金額（{unit}）",
        hovermode="x unified", font=PLOTLY_FONT,
        legend=dict(orientation="h", y=1.05), height=380,
    )
    return fig


def annual_summary_table(ing_id: str, axis1: str, axis2: str, currency: str, fx: float) -> pd.DataFrame:
    """SKU×年次 集計テーブル（金額は選択通貨）"""
    df = get_sku_fc_df(ing_id, axis1, axis2).copy()
    df["year"] = df["period"].str[:4]
    df["amount"] = convert_amounts(df["amount_jpy"].values, currency, fx)
    unit = "万JPY" if currency == "JPY" else "万USD"

    pivot = (
        df.groupby(["sku_id", "year"])[["units", "amount"]]
        .sum()
        .reset_index()
    )
    pivot["units"] = pivot["units"].round(0).astype(int)
    pivot[f"金額（{unit}）"] = (pivot["amount"] / 10_000).round(1)
    pivot = pivot.rename(columns={"sku_id": "SKU", "year": "年度", "units": "数量（本）"})
    return pivot[["SKU", "年度", "数量（本）", f"金額（{unit}）"]]

"""
GE/BS 販売予測アプリ — ダッシュボード（メインページ）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="GE/BS 販売予測",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.ui.common import (
    db_ok, sidebar_controls,
    load_market_df, get_market_fc, get_pen_fit,
    fig_market_trend, fig_penetration, fig_sku_forecast,
    annual_summary_table, INGREDIENTS, get_default_fx,
    convert_amounts,
)
import numpy as np

# ---------- ガード ----------
if not db_ok():
    st.error("データベースが見つかりません。ターミナルで `python3 scripts/init_db.py` を実行してください。")
    st.stop()

# ---------- サイドバー ----------
ctrl = sidebar_controls(key="dash")
ing_id   = ctrl["ing_id"]
currency = ctrl["currency"]
fx       = ctrl["fx"]
axis1    = ctrl["axis1"]
axis2    = ctrl["axis2"]
ing_name = INGREDIENTS[ing_id]

# ---------- ヘッダー ----------
st.title("💊 GE/BS 販売予測ダッシュボード")
scenario_label = "制度変更加味" if axis1 == "regulatory_adjusted" else "制度変更非加味"
axis2_label    = {"base": "ベース", "optimistic": "楽観", "pessimistic": "悲観"}[axis2]
st.caption(f"対象成分: **{ing_name}（{ing_id}）** ／ シナリオ: **{scenario_label} × {axis2_label}** ／ 通貨: **{currency}**")

# ---------- KPI メトリクス ----------
try:
    from src.ui.common import get_sku_fc_df
    df_fc = get_sku_fc_df(ing_id, axis1, axis2)
    df_fc["amount"] = convert_amounts(df_fc["amount_jpy"].values, currency, fx)
    df_fc["year"] = df_fc["period"].str[:4]

    year_totals = df_fc.groupby("year")["amount"].sum() / 10_000
    years = sorted(year_totals.index)

    pen = get_pen_fit(ing_id)
    market_df = load_market_df(ing_id)
    current_pen = market_df["penetration_rate"].iloc[-1]
    fc_pen_adj = get_sku_fc_df(ing_id, "regulatory_adjusted", axis2)  # dummy for pen

    unit = "万JPY" if currency == "JPY" else "万USD"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        y = years[0] if years else "—"
        v = year_totals.get(y, 0)
        st.metric(f"📦 {y}年 予測合計", f"{v:,.0f} {unit}")
    with col2:
        y = years[1] if len(years) > 1 else "—"
        v = year_totals.get(y, 0)
        prev_v = year_totals.get(years[0], 0) if years else 0
        delta = f"{(v - prev_v) / prev_v * 100:+.1f}%" if prev_v else None
        st.metric(f"📦 {y}年 予測合計", f"{v:,.0f} {unit}", delta=delta)
    with col3:
        y = years[2] if len(years) > 2 else "—"
        v = year_totals.get(y, 0)
        prev_v = year_totals.get(years[1], 0) if len(years) > 1 else 0
        delta = f"{(v - prev_v) / prev_v * 100:+.1f}%" if prev_v else None
        st.metric(f"📦 {y}年 予測合計", f"{v:,.0f} {unit}", delta=delta)
    with col4:
        st.metric(
            "📈 現在 GE/BS 浸透率",
            f"{current_pen:.1%}",
            delta=f"上限予測: {pen['L']:.1%}",
        )
except Exception as e:
    st.warning(f"KPI 計算エラー: {e}")

st.divider()

# ---------- チャートタブ ----------
tab1, tab2, tab3 = st.tabs(["📉 市場トレンド", "📈 浸透率カーブ", "🏷️ SKU 予測"])

with tab1:
    st.plotly_chart(fig_market_trend(ing_id), use_container_width=True)
    with st.expander("データ詳細"):
        df_m = load_market_df(ing_id)
        st.dataframe(df_m.tail(12), use_container_width=True)

with tab2:
    st.plotly_chart(fig_penetration(ing_id, axis1, axis2), use_container_width=True)
    fit = get_pen_fit(ing_id)
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("浸透率上限 L", f"{fit['L']:.1%}")
    col_b.metric("立ち上がり速度 k", f"{fit['k']:.4f}")
    col_c.metric("R²", f"{fit['r2']:.4f}")

with tab3:
    st.plotly_chart(fig_sku_forecast(ing_id, axis1, axis2, currency, fx), use_container_width=True)

st.divider()

# ---------- 年次サマリーテーブル ----------
st.subheader("📋 SKU × 年次 Sell-out 予測サマリー")
tbl = annual_summary_table(ing_id, axis1, axis2, currency, fx)
st.dataframe(
    tbl.style.format({col: "{:,.1f}" for col in tbl.columns if "金額" in col}),
    use_container_width=True,
    hide_index=True,
)

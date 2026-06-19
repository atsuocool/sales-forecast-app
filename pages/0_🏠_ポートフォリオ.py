"""
ポートフォリオ概観ページ
全成分の 36ヶ月予測を一覧で比較。月次運用時のファーストビュー。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="ポートフォリオ概観", page_icon="🏠", layout="wide")

from src.ui.common import (
    db_ok, get_conn, get_default_fx, INGREDIENTS, AXIS2_LABELS,
    load_market_df, get_pen_fit, get_sku_fc_df, convert_amounts, PLOTLY_FONT,
)

if not db_ok():
    st.error("DB が見つかりません。`python3 scripts/init_db.py` を実行してください。")
    st.stop()

# ── サイドバー ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ 設定")
    currency = st.radio("💴 通貨", ["JPY", "USD"], horizontal=True, key="pf_cur")
    fx = get_default_fx()
    if currency == "USD":
        fx = st.number_input("JPY/USD レート", value=float(fx), step=1.0,
                             min_value=50.0, max_value=300.0, key="pf_fx")
    st.divider()
    axis2 = st.radio("📊 シナリオ幅", ["base", "optimistic", "pessimistic"],
                     format_func=lambda x: AXIS2_LABELS[x], horizontal=True, key="pf_ax2")
    axis1 = "regulatory_adjusted"
    st.caption("制度変更: 加味（Adjusted）固定")

unit = "万JPY" if currency == "JPY" else "万USD"

st.title("🏠 ポートフォリオ概観")
st.caption(f"シナリオ: 制度変更加味 × {AXIS2_LABELS[axis2]} ／ 通貨: {currency}")

# ── 全成分データ収集 ──────────────────────────────────────────
@st.cache_data(ttl=300)
def portfolio_data(axis1: str, axis2: str, currency: str, fx: float):
    rows = []
    for ing_id, ing_name in INGREDIENTS.items():
        df_fc = get_sku_fc_df(ing_id, axis1, axis2).copy()
        df_fc["year"]   = df_fc["period"].str[:4]
        df_fc["amount"] = convert_amounts(df_fc["amount_jpy"].values, currency, fx) / 10_000
        yr = df_fc.groupby("year")["amount"].sum()
        years = sorted(yr.index)

        pen_fit = get_pen_fit(ing_id)
        df_m    = load_market_df(ing_id)
        cur_pen = df_m["penetration_rate"].iloc[-1]

        for period in sorted(df_fc["period"].unique()):
            amt = df_fc[df_fc["period"] == period]["amount"].sum()
            rows.append({"period": period, "ing_id": ing_id, "ing_name": ing_name, "amount": amt})

    return pd.DataFrame(rows)

with st.spinner("全成分の予測を計算中..."):
    df_all = portfolio_data(axis1, axis2, currency, fx)

# ── ポートフォリオ KPI ──────────────────────────────────────
df_all["year"] = df_all["period"].str[:4]
pf_yr = df_all.groupby("year")["amount"].sum()
years = sorted(pf_yr.index)

st.subheader("📦 ポートフォリオ合計予測")
cols = st.columns(len(years) + 1)
prev = None
for i, y in enumerate(years):
    v = pf_yr.get(y, 0)
    delta = f"{(v - prev) / prev * 100:+.1f}%" if prev else None
    cols[i].metric(f"{y}年 合計", f"{v:,.0f} {unit}", delta=delta)
    prev = v
cols[-1].metric("3年累計", f"{pf_yr.sum():,.0f} {unit}")

st.divider()

# ── 成分別サマリーテーブル ─────────────────────────────────
st.subheader("📋 成分別 年次予測サマリー")

summary_rows = []
for ing_id, ing_name in INGREDIENTS.items():
    sub   = df_all[df_all["ing_id"] == ing_id]
    yr    = sub.groupby("year")["amount"].sum()
    pen   = get_pen_fit(ing_id)
    df_m  = load_market_df(ing_id)
    cur_p = df_m["penetration_rate"].iloc[-1]
    row = {"成分": f"{ing_name}（{ing_id}）", "現在浸透率": f"{cur_p:.1%}", f"浸透率上限L": f"{pen['L']:.1%}"}
    for y in years:
        row[f"{y}({unit})"] = round(yr.get(y, 0), 0)
    summary_rows.append(row)

df_summary = pd.DataFrame(summary_rows)
amount_cols = [c for c in df_summary.columns if unit in c]
st.dataframe(
    df_summary.style.format({c: "{:,.0f}" for c in amount_cols}),
    use_container_width=True, hide_index=True,
)

st.divider()

# ── ポートフォリオ 月次積み上げチャート ──────────────────────
st.subheader("📈 月次予測（成分別積み上げ）")

fig = go.Figure()
colors = {"ING01": "#3B82F6", "ING02": "#EF4444", "ING03": "#10B981", "ING04": "#F59E0B"}
periods = sorted(df_all["period"].unique())

for ing_id, ing_name in INGREDIENTS.items():
    sub = df_all[df_all["ing_id"] == ing_id].sort_values("period")
    fig.add_trace(go.Bar(
        x=sub["period"],
        y=sub["amount"],
        name=f"{ing_name}（{ing_id}）",
        marker_color=colors.get(ing_id, "#94A3B8"),
    ))

fig.update_layout(
    barmode="stack",
    xaxis_title="月", yaxis_title=f"金額（{unit}）",
    hovermode="x unified", font=PLOTLY_FONT,
    legend=dict(orientation="h", y=1.05), height=420,
    title=f"ポートフォリオ月次 Sell-out 予測（{unit}、積み上げ）",
)
st.plotly_chart(fig, use_container_width=True)

# ── 成分別 浸透率一覧 ─────────────────────────────────────
st.divider()
st.subheader("📊 成分別 浸透率サマリー")

pen_cols = st.columns(4)
for i, (ing_id, ing_name) in enumerate(INGREDIENTS.items()):
    p = get_pen_fit(ing_id)
    df_m = load_market_df(ing_id)
    cur_pen = df_m["penetration_rate"].iloc[-1]
    with pen_cols[i]:
        st.metric(ing_name, f"{cur_pen:.1%}", delta=f"上限: {p['L']:.1%}")
        pct = cur_pen / p["L"] if p["L"] > 0 else 0
        st.progress(min(pct, 1.0), text=f"飽和度 {pct:.0%}")

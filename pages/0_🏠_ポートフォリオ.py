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

_COLORS = {"ING01": "#3B82F6", "ING02": "#EF4444", "ING03": "#10B981", "ING04": "#F59E0B"}

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
    st.divider()
    filter_range = st.checkbox("📅 表示期間を絞り込む", value=False, key="pf_filter")

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

@st.cache_data(ttl=300)
def load_actual_by_ingredient(currency: str, fx: float) -> pd.DataFrame:
    """sellout_data を成分×月次にロールアップして通貨換算した実績 DataFrame を返す。"""
    rows = get_conn().execute("""
        SELECT p.ingredient_id AS ing_id, sd.period,
               SUM(sd.amount_jpy) AS amount_jpy
        FROM sellout_data sd
        JOIN skus s ON sd.sku_id = s.sku_id
        JOIN products p ON s.product_id = p.product_id
        GROUP BY p.ingredient_id, sd.period
        ORDER BY p.ingredient_id, sd.period
    """).fetchall()
    df = pd.DataFrame(rows, columns=["ing_id", "period", "amount_jpy"])
    df["amount"] = convert_amounts(df["amount_jpy"].values, currency, fx) / 10_000
    return df


with st.spinner("全成分の予測を計算中..."):
    df_all    = portfolio_data(axis1, axis2, currency, fx)
    df_actual = load_actual_by_ingredient(currency, fx)

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

# ── ポートフォリオ 月次積み上げチャート（実績 + 予測） ──────
st.subheader("📈 月次 Sell-out（実績 + 予測、成分別積み上げ）")

actual_periods = sorted(df_actual["period"].unique())
fc_periods     = sorted(df_all["period"].unique())

# 期間フィルタ（サイドバーの checkbox が ON の場合）
if filter_range and actual_periods and fc_periods:
    all_periods_sorted = actual_periods + fc_periods
    with st.sidebar:
        sel = st.select_slider(
            "表示期間",
            options=all_periods_sorted,
            value=(all_periods_sorted[0], all_periods_sorted[-1]),
            key="pf_range",
        )
    show_start, show_end = sel
    actual_periods = [p for p in actual_periods if show_start <= p <= show_end]
    fc_periods     = [p for p in fc_periods     if show_start <= p <= show_end]

# 実績最終月 → vline の x 位置計算
# Plotly の棒グラフはカテゴリを出現順に 0, 1, 2… と割り振る。
# 実績トレースを先に追加するので、実績が 0〜(N_actual-1)、予測が N_actual〜 のインデックスになる。
n_actual = len(actual_periods)
vline_x  = n_actual - 0.5   # 実績最終棒と予測最初棒の境目

fig = go.Figure()

# ── 実績トレース（ソリッド・高 opacity） ─────────────────────
for ing_id, ing_name in INGREDIENTS.items():
    sub = df_actual[(df_actual["ing_id"] == ing_id) &
                    (df_actual["period"].isin(actual_periods))].sort_values("period")
    if sub.empty:
        continue
    fig.add_trace(go.Bar(
        x=sub["period"],
        y=sub["amount"],
        name=f"{ing_name}（{ing_id}）",
        marker=dict(color=_COLORS[ing_id]),
        legendgroup=ing_id,
        showlegend=True,
        hovertemplate=f"<b>{ing_name}</b> 実績: %{{y:,.0f}} {unit}<extra></extra>",
    ))

# ── 予測トレース（ハッチング・低 opacity） ───────────────────
for ing_id, ing_name in INGREDIENTS.items():
    sub = df_all[(df_all["ing_id"] == ing_id) &
                 (df_all["period"].isin(fc_periods))].sort_values("period")
    if sub.empty:
        continue
    fig.add_trace(go.Bar(
        x=sub["period"],
        y=sub["amount"],
        name=f"{ing_name} 予測",  # legendgroup で実績と紐付け
        marker=dict(
            color=_COLORS[ing_id],
            opacity=0.55,
            pattern=dict(shape="/", size=6, solidity=0.3),
        ),
        legendgroup=ing_id,
        showlegend=False,   # 実績凡例と重複させない
        hovertemplate=f"<b>{ing_name}</b> 予測: %{{y:,.0f}} {unit}<extra></extra>",
    ))

# ── 凡例補助：「予測」アイコン ────────────────────────────
fig.add_trace(go.Bar(
    x=[None], y=[None],
    name="予測（推計）",
    marker=dict(color="#64748B", opacity=0.55, pattern=dict(shape="/", size=6, solidity=0.3)),
    showlegend=True,
))

# ── 境界線 ─────────────────────────────────────────────────
if n_actual > 0 and fc_periods:
    fig.add_vline(x=vline_x, line_dash="dash", line_color="#64748B",
                  line_width=1.5, opacity=0.8)
    fig.add_annotation(
        x=vline_x, y=1.0, yref="paper",
        xanchor="left", text="  予測開始",
        showarrow=False, font=dict(color="#64748B", size=11),
    )

fig.update_layout(
    barmode="stack",
    xaxis=dict(
        type="category",    # 文字列期間を日時と誤認識させない
        title="月",
        tickangle=-45,
        tickfont=dict(size=9),
        nticks=20,          # 表示 tick 数を抑制
    ),
    yaxis_title=f"金額（{unit}）",
    hovermode="x unified", font=PLOTLY_FONT,
    legend=dict(orientation="h", y=1.08), height=500,
    title=f"ポートフォリオ月次 Sell-out（{unit}、積み上げ）",
    bargap=0.05,
    margin=dict(b=80),
)
st.plotly_chart(fig, use_container_width=True)

st.caption(
    f"実績: {actual_periods[0] if actual_periods else '—'} 〜 {actual_periods[-1] if actual_periods else '—'}　"
    f"予測: {fc_periods[0] if fc_periods else '—'} 〜 {fc_periods[-1] if fc_periods else '—'}（{AXIS2_LABELS[axis2]}、制度変更加味）"
)

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

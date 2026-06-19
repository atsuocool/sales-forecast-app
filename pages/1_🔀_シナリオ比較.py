"""
シナリオ比較ページ
制度変更加味（Adjusted）vs 非加味（Organic）を並べて比較し、影響額を算出する。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="シナリオ比較", page_icon="🔀", layout="wide")

from src.ui.common import (
    db_ok, sidebar_controls,
    load_market_df, get_pen_fc, get_sku_fc_df,
    fig_penetration, INGREDIENTS, PLOTLY_FONT, convert_amounts,
)

if not db_ok():
    st.error("DB が見つかりません。")
    st.code(st.session_state.get("_db_last_error", "詳細不明（traceback なし）"))
    st.stop()

# ---------- サイドバー（軸1 は比較対象なので非表示） ----------
ctrl = sidebar_controls(show_axis1=False, key="scen")
ing_id   = ctrl["ing_id"]
currency = ctrl["currency"]
fx       = ctrl["fx"]
axis2    = ctrl["axis2"]
ing_name = INGREDIENTS[ing_id]
unit     = "万JPY" if currency == "JPY" else "万USD"

st.title("🔀 シナリオ比較")
st.caption(
    f"成分: **{ing_name}（{ing_id}）** ／ 軸2: **{ctrl['axis2']}** ／ 通貨: **{currency}**"
)
st.info(
    "**軸1（制度変更 加味 vs 非加味）** を並べて比較します。  \n"
    "差分＝「制度変更による影響額・浸透率上乗せ量」を自動算出します。",
    icon="ℹ️",
)

# ---------- 浸透率比較チャート ----------
st.subheader("📈 浸透率カーブ比較（加味 vs 非加味）")

df_m = load_market_df(ing_id)
fc_x = [p for p in
        __import__("src.ui.common", fromlist=["get_market_fc"]).get_market_fc(ing_id)["periods"]]

fc_adj  = get_pen_fc(ing_id, "regulatory_adjusted",  axis2)
fc_exc  = get_pen_fc(ing_id, "regulatory_excluded",  axis2)
actual_x = df_m["period"].tolist()

fig_pen = go.Figure()
fig_pen.add_trace(go.Scatter(
    x=actual_x, y=[v * 100 for v in df_m["penetration_rate"]],
    mode="markers", name="実績", marker=dict(color="#64748B", size=5),
))
fig_pen.add_trace(go.Scatter(
    x=fc_x, y=[v * 100 for v in fc_exc],
    mode="lines", name="非加味（Organic）",
    line=dict(color="#2563EB", width=2.5),
))
fig_pen.add_trace(go.Scatter(
    x=fc_x, y=[v * 100 for v in fc_adj],
    mode="lines", name="加味（Regulatory-Adjusted）",
    line=dict(color="#DC2626", width=2.5),
))
# 乖離帯
fig_pen.add_trace(go.Scatter(
    x=fc_x + fc_x[::-1],
    y=[v * 100 for v in fc_adj] + [v * 100 for v in fc_exc][::-1],
    fill="toself", fillcolor="rgba(220,38,38,0.10)",
    line=dict(color="rgba(0,0,0,0)"), name="制度変更による上乗せ幅",
))
fig_pen.add_vline(x=actual_x[-1], line_dash="dot", line_color="#94A3B8", opacity=0.5)
fig_pen.add_annotation(x=actual_x[-1], y=1.0, yref="paper", xanchor="left",
                       text="  予測開始", showarrow=False, font=dict(color="#94A3B8", size=11))
fig_pen.update_layout(
    xaxis_title="月", yaxis_title="浸透率（%）",
    yaxis=dict(tickformat=".0f", ticksuffix="%"),
    hovermode="x unified", font=PLOTLY_FONT,
    legend=dict(orientation="h", y=1.08), height=400,
)
st.plotly_chart(fig_pen, use_container_width=True)

# 乖離の数値テーブル
gaps = [(p, exc * 100, adj * 100, (adj - exc) * 100)
        for p, exc, adj in zip(fc_x, fc_exc, fc_adj)]
df_gap = pd.DataFrame(gaps, columns=["月", "非加味（%）", "加味（%）", "乖離（pp）"])
df_gap = df_gap[df_gap["乖離（pp）"].abs() > 0.01]  # 差が出た月のみ
if not df_gap.empty:
    with st.expander("📊 乖離の数値確認（差が生じた月）"):
        st.dataframe(
            df_gap.style.format({"非加味（%）": "{:.1f}%", "加味（%）": "{:.1f}%", "乖離（pp）": "{:+.2f}pp"}),
            use_container_width=True, hide_index=True,
        )

st.divider()

# ---------- 販売金額比較 ----------
st.subheader("💰 自社 SKU 販売金額比較（加味 vs 非加味）")

df_adj = get_sku_fc_df(ing_id, "regulatory_adjusted", axis2).copy()
df_exc = get_sku_fc_df(ing_id, "regulatory_excluded", axis2).copy()

for df in [df_adj, df_exc]:
    df["year"] = df["period"].str[:4]
    df["amount"] = convert_amounts(df["amount_jpy"].values, currency, fx) / 10_000

adj_year = df_adj.groupby("year")["amount"].sum()
exc_year = df_exc.groupby("year")["amount"].sum()
years_common = sorted(set(adj_year.index) & set(exc_year.index))

fig_amt = go.Figure()
fig_amt.add_trace(go.Bar(
    x=years_common, y=[exc_year[y] for y in years_common],
    name="非加味（Organic）", marker_color="#2563EB",
))
fig_amt.add_trace(go.Bar(
    x=years_common, y=[(adj_year[y] - exc_year[y]) for y in years_common],
    name="制度変更による上乗せ分", marker_color="#DC2626", opacity=0.85,
))
fig_amt.update_layout(
    barmode="stack",
    xaxis_title="年度", yaxis_title=f"金額（{unit}）",
    hovermode="x unified", font=PLOTLY_FONT,
    legend=dict(orientation="h", y=1.05), height=380,
)
st.plotly_chart(fig_amt, use_container_width=True)

# ---------- 影響額テーブル ----------
st.subheader("📋 制度変更による影響額（差分）")

rows = []
for y in years_common:
    a = adj_year[y]
    e = exc_year[y]
    rows.append({
        "年度": y,
        f"加味シナリオ（{unit}）": round(a, 1),
        f"非加味シナリオ（{unit}）": round(e, 1),
        f"影響額（{unit}）": round(a - e, 1),
        "影響率（%）": f"{(a - e) / e * 100:+.1f}%" if e else "—",
    })

df_impact = pd.DataFrame(rows)
st.dataframe(df_impact, use_container_width=True, hide_index=True)

total_impact = sum(adj_year.get(y, 0) - exc_year.get(y, 0) for y in years_common)
st.success(f"**36ヶ月累計 制度変更影響額: {total_impact:+,.1f} {unit}**")

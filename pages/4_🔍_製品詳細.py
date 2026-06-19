"""
製品詳細ページ
成分単位のドリルダウン分析:
  Section 1 – 市場トレンド & 浸透率カーブ
  Section 2 – 月次 Sell-out 実績 + 予測（信頼区間付き）
  Section 3 – SKU 構成比推移
  Section 4 – 要因分解ウォーターフォール
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="製品詳細", page_icon="🔍", layout="wide")

from src.ui.common import (
    db_ok, get_conn, get_default_fx, INGREDIENTS, AXIS2_LABELS,
    load_market_df, get_market_fc, get_pen_fit,
    get_sku_fc_df, convert_amounts, PLOTLY_FONT,
    fig_market_trend, fig_penetration,
    save_shared, shared_default, _SHARED,
)

if not db_ok():
    st.error("DB が見つかりません。`python3 scripts/init_db.py` を実行してください。")
    st.stop()

# ── サイドバー（通貨・制度変更・シナリオ幅のみ; 成分は本体で選択） ──────
_CUR_OPTS = ["JPY", "USD"]
_AX1_OPTS = ["regulatory_adjusted", "regulatory_excluded"]
_AX2_OPTS = ["base", "optimistic", "pessimistic"]

def _idx(lst: list, val: object) -> int:
    return lst.index(val) if val in lst else 0

with st.sidebar:
    st.markdown("## ⚙️ 設定")

    currency = st.radio(
        "💴 通貨", _CUR_OPTS, horizontal=True, key="det_cur",
        index=_idx(_CUR_OPTS, shared_default("cur", "JPY")),
    )
    fx = get_default_fx()
    if currency == "USD":
        fx = st.number_input(
            "JPY/USD レート", value=float(shared_default("fx", fx)),
            step=1.0, min_value=50.0, max_value=300.0, key="det_fx",
        )

    st.divider()
    axis1 = st.radio(
        "📋 制度変更", _AX1_OPTS,
        format_func=lambda x: "加味（Adjusted）" if "adjusted" in x else "非加味（Organic）",
        index=_idx(_AX1_OPTS, shared_default("ax1", "regulatory_adjusted")),
        key="det_ax1",
    )
    axis2 = st.radio(
        "📊 シナリオ幅", _AX2_OPTS,
        format_func=lambda x: AXIS2_LABELS[x],
        horizontal=True,
        index=_idx(_AX2_OPTS, shared_default("ax2", "base")),
        key="det_ax2",
    )

save_shared(cur=currency, fx=fx, ax1=axis1, ax2=axis2)
unit = "万JPY" if currency == "JPY" else "万USD"

# ── ページタイトル & 成分セレクタ ─────────────────────────────────
st.title("🔍 製品詳細")

_ING_OPTIONS: dict = {"全体（ポートフォリオ）": None}
_ING_OPTIONS.update({f"{v}（{k}）": k for k, v in INGREDIENTS.items()})

_default_ing = shared_default("ing", None)
_default_label = next(
    (lbl for lbl, k in _ING_OPTIONS.items() if k == _default_ing),
    "全体（ポートフォリオ）",
)

selected_label = st.selectbox(
    "🔬 表示する成分を選択",
    list(_ING_OPTIONS.keys()),
    index=list(_ING_OPTIONS.keys()).index(_default_label),
    key="det_ing_sel",
)
ing_id = _ING_OPTIONS[selected_label]

if ing_id is not None:
    save_shared(ing=ing_id)

# ══════════════════════════════════════════════════
# 全体（ポートフォリオ）ビュー
# ══════════════════════════════════════════════════
if ing_id is None:
    st.info(
        "ポートフォリオ全体の概観は **🏠 ポートフォリオ** ページをご覧ください。  \n"
        "成分を選択すると、その成分の詳細分析が表示されます。",
        icon="ℹ️",
    )
    st.subheader("📋 成分別 予測サマリー（次 36ヶ月）")
    summary_rows = []
    for iid, iname in INGREDIENTS.items():
        try:
            df_fc = get_sku_fc_df(iid, "regulatory_adjusted", axis2).copy()
            df_fc["year"] = df_fc["period"].str[:4]
            df_fc["amount"] = convert_amounts(df_fc["amount_jpy"].values, currency, fx)
            yr = df_fc.groupby("year")["amount"].sum()
            years = sorted(yr.index)
            pen = get_pen_fit(iid)
            df_m = load_market_df(iid)
            row: dict = {
                "成分": f"{iname}（{iid}）",
                "現在浸透率": f"{df_m['penetration_rate'].iloc[-1]:.1%}",
                "浸透率上限 L": f"{pen['L']:.1%}",
            }
            for y in years:
                row[f"{y} ({unit})"] = round(yr.get(y, 0) / 10_000, 0)
            summary_rows.append(row)
        except Exception:
            pass
    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    st.stop()

# ══════════════════════════════════════════════════
# 個別成分 詳細ビュー
# ══════════════════════════════════════════════════
ing_name = INGREDIENTS[ing_id]
st.caption(
    f"成分: **{ing_name}（{ing_id}）**　"
    f"シナリオ: {'制度変更加味' if axis1 == 'regulatory_adjusted' else '制度変更非加味'} "
    f"× {AXIS2_LABELS[axis2]}　通貨: {currency}"
)

# ──────────────────────────────────────────────────
# Section 1: 市場トレンド & 浸透率カーブ
# ──────────────────────────────────────────────────
st.subheader("📉 市場トレンド & 浸透率カーブ")
col1, col2 = st.columns(2)
with col1:
    st.plotly_chart(fig_market_trend(ing_id), use_container_width=True)
with col2:
    st.plotly_chart(fig_penetration(ing_id, axis1, axis2), use_container_width=True)

# ──────────────────────────────────────────────────
# Section 2: 月次 Sell-out 実績 + 予測（信頼区間付き）
# ──────────────────────────────────────────────────
st.divider()
st.subheader("📊 月次 Sell-out 実績 + 予測")


@st.cache_data(ttl=300)
def _load_actual_ing(ing_id: str, currency: str, fx: float) -> pd.DataFrame:
    rows = get_conn().execute("""
        SELECT sd.period, SUM(sd.amount_jpy) AS amount_jpy
        FROM sellout_data sd
        JOIN skus s ON sd.sku_id = s.sku_id
        JOIN products p ON s.product_id = p.product_id
        WHERE p.ingredient_id = ?
        GROUP BY sd.period
        ORDER BY sd.period
    """, (ing_id,)).fetchall()
    df = pd.DataFrame(rows, columns=["period", "amount_jpy"])
    df["amount"] = convert_amounts(df["amount_jpy"].values, currency, fx) / 10_000
    return df


df_actual_ing = _load_actual_ing(ing_id, currency, fx)

df_fc_ing = get_sku_fc_df(ing_id, axis1, axis2).copy()
df_fc_agg = (
    df_fc_ing.groupby("period")["amount_jpy"].sum()
    .reset_index()
    .sort_values("period")
)
df_fc_agg["amount"] = convert_amounts(df_fc_agg["amount_jpy"].values, currency, fx) / 10_000

# 市場 PI から製品レベルの信頼区間を近似
fc_market = get_market_fc(ing_id)
_fc_units = np.array(fc_market["units"], dtype=float)
_safe     = np.where(_fc_units > 0, _fc_units, 1.0)
_r_lo = np.array(fc_market["lower"], dtype=float) / _safe
_r_hi = np.array(fc_market["upper"], dtype=float) / _safe
_fc_amt  = df_fc_agg["amount"].values
_n       = min(len(_fc_amt), len(_r_lo))
ci_lower = _fc_amt[:_n] * _r_lo[:_n]
ci_upper = _fc_amt[:_n] * _r_hi[:_n]
fc_periods = df_fc_agg["period"].tolist()[:_n]

n_actual_ing = len(df_actual_ing)
vline_x_ing  = n_actual_ing - 0.5

fig_monthly = go.Figure()

fig_monthly.add_trace(go.Bar(
    x=df_actual_ing["period"].tolist(), y=df_actual_ing["amount"].tolist(),
    name="実績 Sell-out", marker=dict(color="#3B82F6"),
    hovertemplate="実績: %{y:,.1f} " + unit + "<extra></extra>",
))
fig_monthly.add_trace(go.Bar(
    x=df_fc_agg["period"].tolist(), y=df_fc_agg["amount"].tolist(),
    name="予測 Sell-out",
    marker=dict(color="#3B82F6", opacity=0.55, pattern=dict(shape="/", size=6, solidity=0.3)),
    hovertemplate="予測: %{y:,.1f} " + unit + "<extra></extra>",
))

if len(fc_periods) > 0:
    fig_monthly.add_trace(go.Scatter(
        x=fc_periods + fc_periods[::-1],
        y=ci_upper.tolist() + ci_lower.tolist()[::-1],
        fill="toself", fillcolor="rgba(59,130,246,0.12)",
        line=dict(color="rgba(0,0,0,0)"), name="80% 予測区間（近似）",
    ))

if n_actual_ing > 0 and fc_periods:
    fig_monthly.add_vline(x=vline_x_ing, line_dash="dash",
                          line_color="#64748B", line_width=1.5, opacity=0.8)
    fig_monthly.add_annotation(
        x=vline_x_ing, y=1.0, yref="paper", xanchor="left",
        text="  予測開始", showarrow=False, font=dict(color="#64748B", size=11),
    )

fig_monthly.update_layout(
    barmode="stack",
    xaxis=dict(type="category", title="月", tickangle=-45, nticks=20),
    yaxis_title=f"Sell-out 金額（{unit}）",
    hovermode="x unified", font=PLOTLY_FONT,
    legend=dict(orientation="h", y=1.08), height=420,
    title=f"月次 Sell-out 予測（{ing_name}）",
    bargap=0.05,
)
st.plotly_chart(fig_monthly, use_container_width=True)
st.caption("※ 80% 予測区間は市場合計レベルの PI を製品売上比で近似。")

# ──────────────────────────────────────────────────
# Section 3: SKU 構成比推移
# ──────────────────────────────────────────────────
st.divider()
st.subheader("🧩 SKU 構成比推移")

sku_rows = get_conn().execute("""
    SELECT s.sku_id
    FROM skus s
    JOIN products p ON s.product_id = p.product_id
    WHERE p.ingredient_id = ?
    ORDER BY s.sku_id
""", (ing_id,)).fetchall()
n_skus = len(sku_rows)

if n_skus <= 1:
    st.info(
        f"**{ing_name}（{ing_id}）** は単一 SKU 製品のため、SKU 構成比の比較分析は対象外です。",
        icon="ℹ️",
    )
else:
    @st.cache_data(ttl=300)
    def _load_sku_mix_actual(ing_id: str) -> pd.DataFrame:
        rows = get_conn().execute("""
            SELECT sd.period, sd.sku_id, SUM(sd.amount_jpy) AS amount_jpy
            FROM sellout_data sd
            JOIN skus s ON sd.sku_id = s.sku_id
            JOIN products p ON s.product_id = p.product_id
            WHERE p.ingredient_id = ?
            GROUP BY sd.period, sd.sku_id
            ORDER BY sd.period, sd.sku_id
        """, (ing_id,)).fetchall()
        return pd.DataFrame(rows, columns=["period", "sku_id", "amount_jpy"])

    df_sku_act = _load_sku_mix_actual(ing_id)
    tot_act = df_sku_act.groupby("period")["amount_jpy"].sum()
    df_sku_act["mix"] = df_sku_act.apply(
        lambda r: r["amount_jpy"] / tot_act[r["period"]] * 100
                  if tot_act[r["period"]] > 0 else 0.0,
        axis=1,
    )

    df_sku_fc = df_fc_ing.copy()
    tot_fc = df_sku_fc.groupby("period")["amount_jpy"].sum()
    df_sku_fc["mix"] = df_sku_fc.apply(
        lambda r: r["amount_jpy"] / tot_fc[r["period"]] * 100
                  if tot_fc[r["period"]] > 0 else 0.0,
        axis=1,
    )

    _SKU_COLORS = ["#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899"]
    n_actual_mix = len(df_sku_act["period"].unique())
    vline_x_mix  = n_actual_mix - 0.5

    fig_mix = go.Figure()
    for i, sku_id in enumerate(sorted(df_sku_act["sku_id"].unique())):
        c = _SKU_COLORS[i % len(_SKU_COLORS)]
        sub_a = df_sku_act[df_sku_act["sku_id"] == sku_id].sort_values("period")
        sub_f = df_sku_fc[df_sku_fc["sku_id"] == sku_id].sort_values("period")
        fig_mix.add_trace(go.Bar(
            x=sub_a["period"].tolist(), y=sub_a["mix"].round(1).tolist(),
            name=sku_id, marker=dict(color=c),
            legendgroup=sku_id, showlegend=True,
            hovertemplate=f"{sku_id} 実績: %{{y:.1f}}%<extra></extra>",
        ))
        fig_mix.add_trace(go.Bar(
            x=sub_f["period"].tolist(), y=sub_f["mix"].round(1).tolist(),
            name=f"{sku_id} 予測",
            marker=dict(color=c, opacity=0.55, pattern=dict(shape="/", size=6, solidity=0.3)),
            legendgroup=sku_id, showlegend=False,
            hovertemplate=f"{sku_id} 予測: %{{y:.1f}}%<extra></extra>",
        ))

    if n_actual_mix > 0:
        fig_mix.add_vline(x=vline_x_mix, line_dash="dash",
                          line_color="#64748B", line_width=1.5, opacity=0.8)
        fig_mix.add_annotation(
            x=vline_x_mix, y=1.0, yref="paper", xanchor="left",
            text="  予測開始", showarrow=False, font=dict(color="#64748B", size=11),
        )

    fig_mix.update_layout(
        barmode="stack",
        xaxis=dict(type="category", title="月", tickangle=-45, nticks=20),
        yaxis=dict(title="構成比（%）", tickformat=".0f", ticksuffix="%", range=[0, 102]),
        hovermode="x unified", font=PLOTLY_FONT,
        legend=dict(orientation="h", y=1.08), height=380,
        title=f"SKU 構成比推移（{ing_name}、実績 + 予測）",
        bargap=0.05,
    )
    st.plotly_chart(fig_mix, use_container_width=True)

# ──────────────────────────────────────────────────
# Section 4: 要因分解ウォーターフォール
# ──────────────────────────────────────────────────
st.divider()
st.subheader("🌊 要因分解 ウォーターフォール")

try:
    # 前期実績: 過去 12 ヶ月合計
    _rows_12m = get_conn().execute("""
        SELECT sd.period, SUM(sd.amount_jpy) AS amount
        FROM sellout_data sd
        JOIN skus s ON sd.sku_id = s.sku_id
        JOIN products p ON s.product_id = p.product_id
        WHERE p.ingredient_id = ?
        GROUP BY sd.period
        ORDER BY sd.period DESC
        LIMIT 12
    """, (ing_id,)).fetchall()
    base_jpy = sum(r[1] for r in _rows_12m)

    # 翌期予測（今後 12 ヶ月）: adjusted / excluded 両シナリオ
    df_fc_adj12 = get_sku_fc_df(ing_id, "regulatory_adjusted", axis2)
    df_fc_exc12 = get_sku_fc_df(ing_id, "regulatory_excluded", axis2)
    _fc_periods12 = sorted(df_fc_adj12["period"].unique())[:12]
    fc_adj_jpy = df_fc_adj12[df_fc_adj12["period"].isin(_fc_periods12)]["amount_jpy"].sum()
    fc_exc_jpy = df_fc_exc12[df_fc_exc12["period"].isin(_fc_periods12)]["amount_jpy"].sum()

    organic_jpy    = fc_exc_jpy - base_jpy       # 市場成長 + 浸透率変化（制度変更除く）
    regulatory_jpy = fc_adj_jpy - fc_exc_jpy     # 制度変更の純影響

    def _to_unit(jpy: float) -> float:
        return round(convert_amounts(np.array([jpy]), currency, fx)[0] / 10_000, 1)

    base_u = _to_unit(base_jpy)
    org_u  = _to_unit(organic_jpy)
    reg_u  = _to_unit(regulatory_jpy)
    tot_u  = _to_unit(fc_adj_jpy)

    _measures = ["absolute", "relative", "relative", "total"]
    _labels   = ["前期実績\n(過去12ヶ月)", "市場成長・\n浸透率変化", "制度変更\n影響", "翌期予測\n(次12ヶ月)"]
    _values   = [base_u, org_u, reg_u, tot_u]
    _texts    = [
        f"{base_u:,.1f}",
        f"{org_u:+,.1f}",
        f"{reg_u:+,.1f}",
        f"{tot_u:,.1f}",
    ]

    fig_wf = go.Figure(go.Waterfall(
        orientation="v",
        measure=_measures, x=_labels, y=_values,
        text=_texts, textposition="outside",
        connector=dict(line=dict(color="rgba(100,116,139,0.4)", dash="dot")),
        increasing=dict(marker=dict(color="#16A34A")),
        decreasing=dict(marker=dict(color="#DC2626")),
        totals=dict(marker=dict(color="#2563EB")),
    ))
    fig_wf.update_layout(
        title=f"要因分解ウォーターフォール（{ing_name}、{unit}）",
        xaxis_title="要因", yaxis_title=f"金額（{unit}）",
        font=PLOTLY_FONT, height=420, showlegend=False,
    )
    st.plotly_chart(fig_wf, use_container_width=True)

    # KPI メトリクス
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("前期実績（過去12ヶ月）", f"{base_u:,.1f} {unit}")
    m2.metric(
        "市場成長・浸透率変化", f"{org_u:+,.1f} {unit}",
        delta=f"{org_u / base_u * 100:+.1f}%" if base_u else None,
    )
    m3.metric(
        "制度変更影響", f"{reg_u:+,.1f} {unit}",
        delta=f"{reg_u / base_u * 100:+.1f}%" if base_u else None,
        delta_color="normal",
    )
    m4.metric(
        "翌期予測（次12ヶ月）", f"{tot_u:,.1f} {unit}",
        delta=f"{(tot_u - base_u) / base_u * 100:+.1f}%" if base_u else None,
    )

    st.caption(
        "※ 市場成長・浸透率変化 = 制度変更非加味シナリオ予測 − 前期実績。  \n"
        "※ 制度変更影響 = 加味シナリオ − 非加味シナリオの差分。"
    )

except Exception as e:
    st.error(f"ウォーターフォール計算中にエラーが発生しました: {e}")

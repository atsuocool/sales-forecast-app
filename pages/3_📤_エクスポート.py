"""
エクスポートページ
Excel / PowerPoint / Word トーク原稿の生成・ダウンロード
"""
import sys
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date
import streamlit as st

st.set_page_config(page_title="エクスポート", page_icon="📤", layout="wide")

from src.ui.common import (
    db_ok, get_conn, get_default_fx, get_sku_fc_df, convert_amounts,
    INGREDIENTS, AXIS2_LABELS, sidebar_controls,
)
from src.db.schema import log_forecast

if not db_ok():
    st.error("DB が見つかりません。")
    st.code(st.session_state.get("_db_last_error", "詳細不明（traceback なし）"))
    st.stop()

st.title("📤 エクスポート")
st.caption("予測結果を Excel・PowerPoint・Word（トーク原稿）でダウンロードできます。")

# ── サイドバー ──────────────────────────────────────────────────
ctrl     = sidebar_controls(show_axis1=True, key="exp")
ing_id   = ctrl["ing_id"]
currency = ctrl["currency"]
fx       = ctrl["fx"]
axis1    = ctrl["axis1"]
axis2    = ctrl["axis2"]
ing_name = INGREDIENTS[ing_id]

st.info(
    f"**対象成分**: {ing_name}（{ing_id}）  \n"
    f"**シナリオ**: {'制度変更加味' if axis1 == 'regulatory_adjusted' else '制度変更非加味'} "
    f"× {AXIS2_LABELS[axis2]}  \n"
    f"**通貨**: {currency} / FX: {fx:.1f} JPY/USD",
    icon="ℹ️",
)

def _log_and_record(conn, ing_id, axis1, axis2, currency, fx, kind):
    """エクスポート時に予測ログを記録する。"""
    try:
        import numpy as np
        df_fc = get_sku_fc_df(ing_id, axis1, axis2).copy()
        df_fc["year"]   = df_fc["period"].str[:4]
        df_fc["amount"] = convert_amounts(df_fc["amount_jpy"].values, currency, fx)
        yr = df_fc.groupby("year")["amount"].sum()
        years = sorted(yr.index)
        log_forecast(conn, ing_id, axis1, axis2, currency,
                     float(yr.get(years[0], 0)) if years else 0,
                     float(yr.get(years[1], 0)) if len(years) > 1 else 0,
                     float(yr.get(years[2], 0)) if len(years) > 2 else 0,
                     kind)
    except Exception:
        pass  # ログ失敗はサイレントに無視

st.divider()

# ── セッションステート: 生成済みファイルを保持（rerun をまたいでダウンロードボタンを安定表示） ──
# Streamlit 1.39+ で st.download_button の on_click='rerun' がデフォルトになったため、
# ダウンロードボタンを if st.button(): の内側に置くと rerun 後にトークンが orphan になり
# ブラウザが UUID をファイル名として使ってしまう。session_state で保持して外に出す。
for _k in ("xl_file", "ppt_file", "doc_file"):
    if _k not in st.session_state:
        st.session_state[_k] = None

# 設定が変わったらキャッシュをクリア
_cache_key = (ing_id, axis1, axis2, currency, round(fx, 2))
if st.session_state.get("_exp_cache_key") != _cache_key:
    st.session_state["_exp_cache_key"] = _cache_key
    st.session_state["xl_file"]  = None
    st.session_state["ppt_file"] = None
    st.session_state["doc_file"] = None

# ── 3列レイアウト ───────────────────────────────────────────────
col_xl, col_ppt, col_doc = st.columns(3)

# ---------- Excel ----------
with col_xl:
    st.subheader("📊 Excel")
    st.markdown(
        "**含まれるシート**\n"
        "- 月次予測（加味 vs 非加味）\n"
        "- 年次サマリー（SKU別）\n"
        "- シナリオ比較・影響額"
    )
    if st.button("Excel を生成", type="primary", key="gen_xl", use_container_width=True):
        with st.spinner("Excel 生成中..."):
            try:
                from src.export.excel_exporter import generate_excel
                _data = generate_excel(get_conn(), ing_id, axis1, axis2, currency, fx)
                _fname = f"forecast_{ing_id}_{axis2}_{currency}_{date.today()}.xlsx"
                assert _fname.endswith(".xlsx"), "拡張子チェック失敗"
                _log_and_record(get_conn(), ing_id, axis1, axis2, currency, fx, "Excel")
                st.session_state["xl_file"] = (_data, _fname)
                st.rerun()
            except Exception as e:
                st.error(f"生成エラー: {e}")
    if st.session_state["xl_file"]:
        _d, _f = st.session_state["xl_file"]
        st.download_button(
            label="⬇️ Excel をダウンロード",
            data=bytes(_d),
            file_name=_f,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_xl",
            on_click="ignore",
            use_container_width=True,
        )
        st.caption(f"📄 {_f}")

# ---------- PowerPoint ----------
with col_ppt:
    st.subheader("📑 PowerPoint")
    st.markdown(
        "**含まれるスライド**\n"
        "- 表紙\n"
        "- ① サマリー KPI\n"
        "- ② 市場トレンド\n"
        "- ③ 自社 SKU 予測\n"
        "- ④ シナリオ比較\n"
        "- ⑤ 要因分解（ウォーターフォール）\n"
        "- ⑥ リスク・アクション"
    )
    if st.button("PowerPoint を生成", type="primary", key="gen_ppt", use_container_width=True):
        with st.spinner("PowerPoint 生成中（グラフ描画に数秒かかります）..."):
            try:
                from src.export.pptx_exporter import generate_pptx
                _data = generate_pptx(get_conn(), ing_id, axis2, currency, fx)
                _fname = f"forecast_{ing_id}_{axis2}_{currency}_{date.today()}.pptx"
                assert _fname.endswith(".pptx"), "拡張子チェック失敗"
                _log_and_record(get_conn(), ing_id, axis1, axis2, currency, fx, "PowerPoint")
                st.session_state["ppt_file"] = (_data, _fname)
                st.rerun()
            except Exception as e:
                st.error(f"生成エラー: {e}")
    if st.session_state["ppt_file"]:
        _d, _f = st.session_state["ppt_file"]
        st.download_button(
            label="⬇️ PowerPoint をダウンロード",
            data=bytes(_d),
            file_name=_f,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            key="dl_ppt",
            on_click="ignore",
            use_container_width=True,
        )
        st.caption(f"📄 {_f}")

# ---------- Word ----------
with col_doc:
    st.subheader("📝 Word（トーク原稿）")
    st.markdown(
        "**含まれるセクション**\n"
        "- ① 予測の目的・対象\n"
        "- ② 市場トレンド解説\n"
        "- ③ 浸透率カーブ解説\n"
        "- ④ SKU 配分の考え方\n"
        "- ⑤ シナリオ比較解説\n"
        "- ⑥ 要因分解解説\n"
        "- ⑦ 想定 Q&A\n"
        "- 用語集（グロッサリー）"
    )
    detail = st.radio("詳細度", ["standard", "detailed"],
                      format_func=lambda x: "標準" if x == "standard" else "詳細",
                      horizontal=True, key="doc_detail")
    if st.button("Word を生成", type="primary", key="gen_doc", use_container_width=True):
        with st.spinner("Word 生成中..."):
            try:
                from src.export.word_exporter import generate_word
                _data = generate_word(get_conn(), ing_id, axis1, axis2, detail)
                _fname = f"talk_script_{ing_id}_{axis2}_{date.today()}.docx"
                assert _fname.endswith(".docx"), "拡張子チェック失敗"
                _log_and_record(get_conn(), ing_id, axis1, axis2, currency, fx, "Word")
                st.session_state["doc_file"] = (_data, _fname)
                st.rerun()
            except Exception as e:
                st.error(f"生成エラー: {e}")
    if st.session_state["doc_file"]:
        _d, _f = st.session_state["doc_file"]
        st.download_button(
            label="⬇️ Word をダウンロード",
            data=bytes(_d),
            file_name=_f,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="dl_doc",
            on_click="ignore",
            use_container_width=True,
        )
        st.caption(f"📄 {_f}")

st.divider()

# ── ヒント ──────────────────────────────────────────────────────
with st.expander("📌 ファイル利用のヒント"):
    st.markdown("""
**Excel**:
- 「シナリオ比較」シートの最下行に 36ヶ月累計影響額が表示されます。
- 数値をコピーして社内 Excel テンプレートに貼り付けてご利用ください。

**PowerPoint**:
- スライド⑥「リスク・アクション」は手動で編集してください。
- グラフはラスター画像として埋め込まれています。編集する場合は再生成をお勧めします。

**Word（トーク原稿）**:
- そのまま読み上げ／プレゼン前の確認に使えます。
- Q&A セクションは想定質疑の参考例です。状況に応じて追記・修正してください。
- 用語集は配布資料として後段に付与できます。
""")

"""
データ管理ページ
DB 状態確認 + CSV ファイルアップロード + キャッシュクリア
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import tempfile
import streamlit as st

st.set_page_config(page_title="データ管理", page_icon="📁", layout="wide")

from src.ui.common import get_conn, db_ok
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.pipeline.inventory_loader import (
    load_sellin, load_sellout, load_inventory, load_regulatory_events,
)
from src.pipeline.fx_loader import load_fx_rates

st.title("📁 データ管理")

# ---------- DB 状態 ----------
st.subheader("🗄️ データベース状態")

if not db_ok():
    st.error("DB が見つかりません。ターミナルで `python3 scripts/init_db.py` を実行してください。")
    st.stop()

conn = get_conn()

status_queries = {
    "市場データ（IQVIA）":  ("market_data",     "period"),
    "Sell-in":             ("sellin_data",      "period"),
    "Sell-out":            ("sellout_data",     "period"),
    "卸別在庫":             ("inventory_data",  "period"),
    "制度イベント":          ("regulatory_events", "event_date"),
    "為替レート":            ("fx_rates",        "period"),
}

cols = st.columns(len(status_queries))
for col, (label, (table, date_col)) in zip(cols, status_queries.items()):
    try:
        row = conn.execute(
            f"SELECT COUNT(*), MIN({date_col}), MAX({date_col}) FROM {table}"
        ).fetchone()
        n, d_min, d_max = row[0], row[1] or "—", row[2] or "—"
        col.metric(label, f"{n:,} 件", f"{d_min} 〜 {d_max}")
    except Exception as e:
        col.metric(label, "エラー", str(e))

st.divider()

# ---------- キャッシュクリア ----------
st.subheader("🔄 キャッシュ管理")
col_a, col_b = st.columns([1, 3])
with col_a:
    if st.button("キャッシュをクリア", type="secondary"):
        st.cache_data.clear()
        st.success("キャッシュをクリアしました。次回アクセス時にデータを再取得します。")
with col_b:
    st.caption("データを更新した後は、キャッシュをクリアしてください（TTL=5分でも自動失効します）。")

st.divider()

# ---------- ファイルアップロード ----------
st.subheader("📤 データファイルのアップロード")
st.info("CSV ファイル（UTF-8 または UTF-8 BOM）をアップロードします。既存データは INSERT OR IGNORE で重複スキップされます。", icon="ℹ️")

upload_configs = [
    ("IQVIA 市場データ",   load_iqvia,              "iqvia_market_data.csv の形式"),
    ("Sell-in データ",     load_sellin,             "period, sku_id, distributor, quantity, amount_jpy"),
    ("Sell-out データ",    load_sellout,            "period, sku_id, facility_type, quantity, amount_jpy"),
    ("卸別在庫データ",      load_inventory,          "period, sku_id, distributor, ending_inventory_qty, ending_inventory_amount_jpy"),
    ("制度イベントマスタ",  load_regulatory_events,  "event_date, event_type, impact_scope, impact_target, impact_parameter, impact_value, effect_lag_months, memo"),
    ("為替レート",          load_fx_rates,           "rate_type, period, jpy_per_usd, updated_by, updated_at"),
]

for label, loader_fn, hint in upload_configs:
    with st.expander(f"📄 {label}"):
        st.caption(f"列: `{hint}`")
        uploaded = st.file_uploader(f"{label} CSV", type="csv", key=f"upload_{label}")
        if uploaded is not None:
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = tmp.name
            try:
                n = loader_fn(get_conn(), tmp_path)
                st.success(f"✅ アップロード成功。現在の {label} 件数: **{n:,} 件**")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"❌ エラー: {e}")

st.divider()

# ---------- DB 初期化（フルリセット） ----------
st.subheader("⚠️ DB 初期化（サンプルデータで再構築）")
st.warning(
    "現在のデータをすべて削除し、`docs/sample_data/` のサンプルデータで再構築します。"
    "運用データがある場合は実行しないでください。",
    icon="⚠️",
)
if st.button("🗑️ DB を初期化する（サンプルデータで再構築）", type="primary"):
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "scripts/init_db.py"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent),
    )
    if result.returncode == 0:
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("✅ DB を初期化しました。")
        st.code(result.stdout)
    else:
        st.error("❌ 初期化に失敗しました。")
        st.code(result.stderr)

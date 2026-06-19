"""
データ管理ページ
DB 状態確認 + CSV ファイルアップロード + キャッシュクリア
"""
import sys
import traceback
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
    st.error("DB が見つかりません。")
    st.code(st.session_state.get("_db_last_error", "詳細不明（traceback なし）"))
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

# ---------- 月次運用フロー ----------
st.subheader("📅 月次運用チェックリスト")
st.caption("毎月のデータ更新・予測確認の標準フロー")

with st.expander("📋 月次運用ステップ（クリックで展開）", expanded=True):
    step_status = []

    # 各テーブルのデータ鮮度確認
    freshness = {}
    for tbl, date_col in [("market_data","period"),("sellin_data","period"),
                           ("sellout_data","period"),("inventory_data","period"),
                           ("regulatory_events","event_date"),("fx_rates","period")]:
        try:
            row = conn.execute(f"SELECT MAX({date_col}) FROM {tbl}").fetchone()
            freshness[tbl] = row[0] or "データなし"
        except Exception:
            freshness[tbl] = "エラー"

    import datetime
    current_ym = datetime.date.today().strftime("%Y-%m")

    checklist = [
        ("IQVIA 市場データの更新",
         freshness.get("market_data","?"),
         "毎月末にエクスポートされた最新月のデータをアップロードしてください。"),
        ("Sell-in データの更新",
         freshness.get("sellin_data","?"),
         "社内システムから SKU×卸 月次 Sell-in データを取得してアップロードします。"),
        ("Sell-out データの更新",
         freshness.get("sellout_data","?"),
         "社内システムから SKU×施設区分 月次 Sell-out データを取得してアップロードします。"),
        ("卸別在庫データの更新",
         freshness.get("inventory_data","?"),
         "月末在庫データを更新し、在庫日数（DOI）の異常値を確認します。"),
        ("為替レートの確認",
         freshness.get("fx_rates","?"),
         "USD 表示を使用する場合、forecast_assumption レートを最新値に更新してください。"),
        ("制度イベントの確認",
         freshness.get("regulatory_events","?"),
         "新たな薬価改定・使用促進策が発表された場合、イベントマスタを更新します。"),
    ]

    for i, (task, last_period, note) in enumerate(checklist, 1):
        ok = last_period >= current_ym[:7] if last_period not in ("データなし","エラー","?") else False
        icon = "✅" if ok else "⬜"
        cols = st.columns([0.08, 0.35, 0.18, 0.39])
        cols[0].markdown(f"**{icon}**")
        cols[1].markdown(f"**{i}. {task}**")
        cols[2].markdown(f"`最終: {last_period}`")
        cols[3].caption(note)

    st.markdown("---")
    st.markdown(
        "**更新後の手順:**  \n"
        "① 上の「ファイルアップロード」から新データを投入  \n"
        "② 「キャッシュをクリア」ボタンで予測キャッシュを更新  \n"
        "③ ポートフォリオ概観・ダッシュボードで数値を確認  \n"
        "④ 📤 エクスポートページで月次レポートを生成・配布"
    )

# ---------- 予測ログ ----------
st.divider()
st.subheader("📜 予測ログ（エクスポート履歴）")
try:
    log_rows = conn.execute(
        "SELECT log_id, logged_at, ing_id, axis1, axis2, currency, "
        "ROUND(fc_y1_jpy/10000,0) y1, ROUND(fc_y2_jpy/10000,0) y2, ROUND(fc_y3_jpy/10000,0) y3, triggered_by "
        "FROM forecast_log ORDER BY log_id DESC LIMIT 20"
    ).fetchall()
    if log_rows:
        import pandas as pd
        df_log = pd.DataFrame(log_rows, columns=["ID","日時","成分","軸1","軸2","通貨",
                                                   "Y1(万JPY)","Y2(万JPY)","Y3(万JPY)","出力種別"])
        st.dataframe(df_log, use_container_width=True, hide_index=True)
    else:
        st.info("エクスポートを実行すると、ここに予測ログが記録されます。")
except Exception:
    st.info("forecast_log テーブルが未作成です。`python3 scripts/init_db.py` を再実行してください。")

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

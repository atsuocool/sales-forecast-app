import os
import sys
from pathlib import Path

# __file__ を resolve() して絶対パスを確定（Streamlit Cloud での symlink 対策）
_BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BASE_DIR))

from src.db.connection import get_connection
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.pipeline.inventory_loader import (
    load_sellin, load_sellout, load_inventory, load_regulatory_events
)
from src.pipeline.fx_loader import load_fx_rates

# CSVのパスを __file__ 基準の絶対パスで解決
DATA_DIR = str(_BASE_DIR / "docs" / "sample_data")
DB_PATH  = os.environ.get("DB_PATH", "/tmp/pharma_forecast.db")


def run_init(db_path: str = DB_PATH, data_dir: str = DATA_DIR) -> None:
    """DB 初期化 + サンプルデータロード。

    app.py の起動時自動初期化からも呼ばれる。
    db_path の親ディレクトリが存在しない場合は自動作成する。
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)

    create_all_tables(conn)

    load_masters(conn, data_dir)
    load_iqvia(conn, f"{data_dir}/iqvia_market_data.csv")
    load_sellin(conn, f"{data_dir}/sellin_data.csv")
    load_sellout(conn, f"{data_dir}/sellout_data.csv")
    load_inventory(conn, f"{data_dir}/inventory_data.csv")

    conn.execute("DELETE FROM regulatory_events")   # 重複防止: 毎回クリアしてから投入
    conn.commit()
    load_regulatory_events(conn, f"{data_dir}/regulatory_events_sample.csv")
    load_fx_rates(conn, f"{data_dir}/fx_rates_sample.csv")

    conn.close()


def main():
    print(f"DB初期化: {DB_PATH}")
    run_init(db_path=DB_PATH, data_dir=DATA_DIR)
    print("完了。")


if __name__ == "__main__":
    main()

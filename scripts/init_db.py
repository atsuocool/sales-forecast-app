import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import get_connection
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.pipeline.inventory_loader import (
    load_sellin, load_sellout, load_inventory, load_regulatory_events
)
from src.pipeline.fx_loader import load_fx_rates

DATA_DIR = "docs/sample_data"
DB_PATH  = "data/pharma_forecast.db"


def main():
    print(f"DB初期化: {DB_PATH}")
    conn = get_connection(DB_PATH)

    print("テーブル作成...")
    create_all_tables(conn)

    print("階層マスタをロード中...")
    counts = load_masters(conn, DATA_DIR)
    print(f"  疾患領域 (therapeutic_areas): {counts['therapeutic_areas']}")
    print(f"  成分     (ingredients):       {counts['ingredients']}")
    print(f"  製品     (products):          {counts['products']}")
    print(f"  SKU      (skus):              {counts['skus']}")

    print("IQVIAデータをロード中...")
    n = load_iqvia(conn, f"{DATA_DIR}/iqvia_market_data.csv")
    print(f"  market_data 行数: {n}")

    print("Sell-inデータをロード中...")
    n = load_sellin(conn, f"{DATA_DIR}/sellin_data.csv")
    print(f"  sellin_data 行数: {n}")

    print("Sell-outデータをロード中...")
    n = load_sellout(conn, f"{DATA_DIR}/sellout_data.csv")
    print(f"  sellout_data 行数: {n}")

    print("卸別在庫データをロード中...")
    n = load_inventory(conn, f"{DATA_DIR}/inventory_data.csv")
    print(f"  inventory_data 行数: {n}")

    print("制度イベントマスタをロード中...")
    n = load_regulatory_events(conn, f"{DATA_DIR}/regulatory_events_sample.csv")
    print(f"  regulatory_events 行数: {n}")

    print("為替レートをロード中...")
    n = load_fx_rates(conn, f"{DATA_DIR}/fx_rates_sample.csv")
    print(f"  fx_rates 行数: {n}")

    conn.close()
    print("\n完了。")


if __name__ == "__main__":
    main()

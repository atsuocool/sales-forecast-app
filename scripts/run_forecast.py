import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import get_connection
from src.forecast.market_forecast import aggregate_market, MarketForecaster, backtest

DB_PATH = "data/pharma_forecast.db"


def main():
    conn = get_connection(DB_PATH)
    ingredients = conn.execute(
        "SELECT ingredient_id, name FROM ingredients ORDER BY ingredient_id"
    ).fetchall()

    print("=" * 65)
    print("バックテスト結果（直近12ヶ月ホールドアウト）")
    print("=" * 65)
    for row in ingredients:
        ing_id, name = row["ingredient_id"], row["name"]
        result = backtest(conn, ing_id, test_periods=12)
        print(f"\n{name} ({ing_id})")
        print(f"  訓練: {result.train_periods}ヶ月 / テスト: {result.test_periods}ヶ月")
        print(f"  MAPE(数量): {result.mape_units:5.1f}%   RMSE(数量): {result.rmse_units:>14,.0f}")
        print(f"  MAPE(金額): {result.mape_amount:5.1f}%   RMSE(金額): {result.rmse_amount:>14,.0f}円")

    print("\n" + "=" * 65)
    print("36ヶ月フォーキャスト（全成分）")
    print("=" * 65)
    for row in ingredients:
        ing_id, name = row["ingredient_id"], row["name"]
        df     = aggregate_market(conn, ing_id)
        result = MarketForecaster(ing_id, horizon=36).fit(df).predict()
        y1 = result.forecast_units[:12].sum()
        y2 = result.forecast_units[12:24].sum()
        y3 = result.forecast_units[24:36].sum()
        print(f"\n{name}")
        print(f"  1年目 ({result.periods[0]}〜{result.periods[11]}): {y1:>12,.0f} 単位")
        print(f"  2年目 ({result.periods[12]}〜{result.periods[23]}): {y2:>12,.0f} 単位")
        print(f"  3年目 ({result.periods[24]}〜{result.periods[35]}): {y3:>12,.0f} 単位")

    conn.close()


if __name__ == "__main__":
    main()

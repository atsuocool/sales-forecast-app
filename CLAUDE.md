# sales-forecast-app — Claude Code 向けプロジェクトガイド

ジェネリック医薬品・バイオシミラーの**SKU単位 36ヶ月販売予測アプリ**。
仕様の原典は `docs/spec.md`（Claude Code 実装用、2026-06-19 作成）。

---

## 1. アプリ概要

**目的**: 疾患領域→成分→製品→SKU の 4 階層で月次販売予測を生成し、制度変更影響の加味/非加味シナリオを比較、経営報告用 PowerPoint・トーク原稿を出力する。

**対象ユーザー**: コマーシャルエクセレンス部門アナリスト（自分）、営業企画・経営層。

**非機能要件のポイント**:
- 社外送信なし（ローカル SQLite 運用）
- パラメータ変更後の再計算は数秒以内
- 予測ロジック（Step 1〜5）は関数単位で分離し、手法差し替えが容易な設計

---

## 2. データ階層とデータソース

```
疾患領域 (Therapeutic Area)
  └─ 成分 (Ingredient)        ← IQVIA 市場データ・浸透率はここで集計
       └─ 製品 (Product)       ← 自社ブランド単位
            └─ SKU             ← 予測の最終出力単位。Sell-in/out/在庫もこの粒度
```

| データソース | 粒度 | 用途 |
|---|---|---|
| IQVIA市場データ | 成分×月次 | 市場トレンド・GE/BS浸透率 |
| Sell-in | SKU×月次×卸 | 出荷実績、在庫変動補正の基礎 |
| Sell-out | SKU×月次×施設区分 | 真の需要シグナル（予測ベース） |
| 卸別月末在庫 | SKU×月次×卸 | Sell-in/out ギャップ実測補正・Days of Inventory |
| 制度イベント | 月次 | 薬価改定・浸透率への制度変更 |
| 為替レート | 月次 | JPY/USD 表示切替用 |

**重要**: 内部計算はすべて **JPY** で保持。表示時のみ換算。

---

## 3. 予測ロジック（5ステップ）

```
Step 1: 成分市場サイズ予測        Holt-Winters (statsmodels ExponentialSmoothing)
Step 2: GE/BS浸透率予測           ロジスティック曲線 (scipy.optimize.curve_fit)
Step 3: 自社 GE/BS シェア予測     線形トレンド (np.polyfit)
Step 4: SKU 構成比予測            線形トレンド + 月次正規化
Step 5: 統合・シナリオ適用         価格係数 × 浸透率調整 × 在庫補正
```

**数式:**

```
SKU Sell-out 数量[t] = 市場総量[t] × 浸透率[t] × 自社シェア[t] × SKU構成比[t]
SKU Sell-out 金額[t] = SKU 数量[t] × 平均単価
```

**バックテスト**: 直近 12 ヶ月 hold-out で MAPE / RMSE 評価。

---

## 4. シナリオ設計（2 軸）

| 軸 | 値 | 内容 |
|---|---|---|
| 軸1: 制度変更 | `regulatory_adjusted` | 薬価改定・浸透率イベント反映あり |
| 軸1: 制度変更 | `regulatory_excluded` | 自然なトレンドのみ（影響額の切り出し用） |
| 軸2: 幅 | `base` | デフォルトパラメータ |
| 軸2: 幅 | `optimistic` | 浸透率上限+α、成長率+α |
| 軸2: 幅 | `pessimistic` | 浸透率上限-α、成長率-α |

差分（adjusted − excluded）が「制度変更による影響額」として自動算出される。

---

## 5. DB スキーマ（SQLite: `data/pharma_forecast.db`）

| テーブル | 主要列 | 備考 |
|---|---|---|
| `therapeutic_areas` | `therapeutic_area_id`, `name` | |
| `ingredients` | `ingredient_id`, `therapeutic_area_id`, `name`, `drug_type` | `drug_type IN ('generic','biosimilar')` |
| `products` | `product_id`, `ingredient_id`, `product_name`, `type` | |
| `skus` | `sku_id`, `product_id`, `package_form`, `package_size`, `strength`, `launch_date` | |
| `market_data` | `period`, `ingredient_id`, `manufacturer_type`, `sales_units`, `sales_amount_jpy`, `generic_biosimilar_penetration_rate` | IQVIA 由来 |
| `sellin_data` | `period`, `sku_id`, `distributor`, `quantity`, `amount_jpy` | |
| `sellout_data` | `period`, `sku_id`, `facility_type`, `quantity`, `amount_jpy` | |
| `inventory_data` | `period`, `sku_id`, `distributor`, `ending_inventory_qty`, `ending_inventory_amount_jpy` | |
| `regulatory_events` | `event_date`, `event_type`, `impact_scope`, `impact_target`, `impact_parameter`, `impact_value`, `effect_lag_months`, `memo` | Step 5 で拡張済み |
| `fx_rates` | `rate_type`, `period`, `jpy_per_usd` | `rate_type IN ('historical','forecast_assumption')` |

**regulatory_events の impact_target:**
- `price` → 価格調整係数（`impact_parameter='price_change_rate'`）
- `penetration` → 浸透率パラメータ（`pen_L_delta` / `pen_k_delta`）、`effect_lag_months` ヶ月後から漸増

---

## 6. コードマップ

```
src/
  db/
    connection.py          get_connection(db_path) → sqlite3.Connection (FK ON, Row factory)
    schema.py              create_all_tables(conn) + _migrate_regulatory_events(conn)
  pipeline/
    master_loader.py       load_masters(conn, data_dir) → counts dict
    iqvia_loader.py        load_iqvia(conn, csv_path) → row count
    inventory_loader.py    load_sellin / load_sellout / load_inventory / load_regulatory_events
  forecast/
    metrics.py             mape(actual, predicted) / rmse(actual, predicted)
    market_forecast.py     aggregate_market(conn, ingredient_id) → DataFrame
                           MarketForecaster.fit(df).predict() → ForecastResult
                           backtest(conn, ingredient_id) → BacktestResult
    penetration.py         PenetrationForecaster.fit(df).predict(horizon, events) → ndarray
                           EventAdjustment(month_offset, ceiling_delta, speed_delta, label)
    own_share.py           aggregate_own_share(conn, ingredient_id) → DataFrame
                           OwnShareForecaster.fit(df).predict(horizon) → ndarray
    sku_mix.py             aggregate_sellout_by_sku(conn, product_id) → DataFrame
                           SkuMixForecaster.fit(df).predict(horizon) → DataFrame
    integrated_forecast.py run_integrated_forecast(conn, ingredient_id, horizon, penetration_events)
                           → List[SkuForecastResult]

scripts/
  init_db.py                    DB 初期化（テーブル作成 + 全データ投入）
  run_forecast.py               全成分の Holt-Winters バックテスト＋36ヶ月予測を表示
  plot_penetration.py           浸透率ロジスティックカーブ + 制度変更シナリオ PNG 出力 → output/
  run_integrated_forecast.py    Step 1〜4 統合 SKU 予測を年次サマリーで表示

tests/
  conftest.py                   mem_conn fixture (in-memory SQLite)
  test_schema.py / test_master_loader.py / test_iqvia_loader.py / test_inventory_loader.py
  test_market_forecast.py / test_penetration.py / test_own_share.py
  test_sku_mix.py / test_integrated_forecast.py
```

---

## 7. サンプルデータ（`docs/sample_data/`）

| ファイル | 内容 |
|---|---|
| `master_therapeutic_areas.csv` | 4 疾患領域（代謝・内分泌/循環器/血液/免疫） |
| `master_ingredients.csv` | 4 成分: ING01=メトホルミン, ING02=アトルバスタチン, ING03=フィルグラスチム, ING04=インフリキシマブ |
| `master_products.csv` | 4 製品（各成分 1 製品） |
| `master_skus.csv` | 7 SKU（PROD01/02 各 2 SKU、PROD03 2 SKU、PROD04 1 SKU） |
| `iqvia_market_data.csv` | 2023-01〜2026-05（41 期間）, 4 メーカー区分 × 4 成分 |
| `sellin_data.csv` | SKU×卸 月次 |
| `sellout_data.csv` | SKU×施設区分 月次 |
| `inventory_data.csv` | SKU×卸 月末在庫 |
| `regulatory_events_sample.csv` | 薬価改定 3 件 (price) + 浸透率イベント 2 件 (penetration) |

---

## 8. 開発ステップと現在の進捗

| Step | 内容 | 状態 |
|---|---|---|
| **Step 1** | データ基盤（SQLite + 階層マスタ + 取込パイプライン） | ✅ 完了・コミット済み |
| **Step 2** | Holt-Winters 市場予測エンジン（バックテスト付き） | ✅ 完了・コミット済み |
| **Step 3** | ロジスティック浸透率モデル + 制度イベント調整 + PNG プロット | ✅ 完了・コミット済み |
| **Step 4** | 自社シェア・SKU 構成比トレンド + 統合 SKU 予測 | ✅ 完了・コミット済み |
| **Step 5** | シナリオ軸実装（制度変更加味/非加味 × ベース/楽観/悲観） | ✅ 完了・コミット済み |
| **Step 6** | 通貨換算（JPY/USD 表示切替、fx_rates テーブル） | ✅ 完了・コミット済み |
| **Step 7** | Streamlit フロントエンド（ダッシュボード/シナリオ比較/データ管理） | ✅ 完了・コミット済み |
| **Step 8** | エクスポート（Excel/PowerPoint/Word トーク原稿） | ✅ 完了・コミット済み |
| **Step 9** | 複数 SKU・製品への展開・運用化 | ✅ 完了・コミット済み |

---

## 9. 実行方法

```bash
# DB 初期化（初回・データ更新時）
python3 scripts/init_db.py

# 全テスト実行
python3 -m pytest tests/ -q

# 市場予測＋バックテスト
python3 scripts/run_forecast.py

# 浸透率カーブ PNG 生成（output/ フォルダ）
python3 scripts/plot_penetration.py

# 統合 SKU 予測（年次サマリー）
python3 scripts/run_integrated_forecast.py
```

---

## 10. 技術メモ（環境固有の注意点）

- **Python 3.9.6 (macOS)**: `X | Y` union 型は非対応 → `Optional[X]` / `Union[X, Y]` を使う
- **statsmodels 0.14**: `ExponentialSmoothing.fit()` の `disp` 引数は削除済み → `fit(optimized=True)` のみ
- **matplotlib 日本語フォント**: `rcParams["font.family"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]`
- **CSV 読み込み**: BOM 付き UTF-8 → `encoding="utf-8-sig"`
- **FK 制約**: 接続後に `PRAGMA foreign_keys = ON` 必須（`get_connection()` 内で実行済み）
- **単価**: amount_jpy / quantity の実績平均で近似（`_avg_unit_price()` in `integrated_forecast.py`）

---

## 11. 出力ファイル

| パス | 内容 |
|---|---|
| `data/pharma_forecast.db` | SQLite DB（.gitignore 対象） |
| `output/penetration_ING01.png` | メトホルミン浸透率カーブ（R²=0.82） |
| `output/penetration_ING02.png` | アトルバスタチン浸透率カーブ（R²=0.88） |
| `output/penetration_ING03.png` | フィルグラスチム浸透率カーブ（R²=0.997, L=57.5%） |
| `output/penetration_ING04.png` | インフリキシマブ浸透率カーブ（R²=0.989, L=43.0%） |

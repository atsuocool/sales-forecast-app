# SKU別販売予測アプリ 仕様書（Excel + Power BI版）

**作成日**: 2026年6月20日
**対象部門**: コマーシャルエクセレンス部門
**対象製品**: ジェネリック医薬品・バイオシミラー
**プラットフォーム**: Microsoft Excel (.xlsm) + Power BI Desktop / Service

---

## 1. プロジェクト概要

### 1.1 目的
ジェネリック医薬品・バイオシミラーのポートフォリオについて、**SKU単位**で**今後36ヶ月の月次販売予測**を生成するシステムを構築する。

計算エンジンとしてExcel（VBA/Power Query/数式）、可視化・レポーティングとしてPower BIを使用する構成とする。

予測には以下を組み込む：
- 当該SKUが属する**疾患領域・成分全体の市場トレンド**（IQVIAデータ）
- 当該SKUが属する成分の**ジェネリック/バイオシミラー浸透率**の推移とその将来カーブ
- 薬価改定・後発品使用促進策など**制度変更の影響**をパラメータとして調整可能にする
- 金額は**日本円(JPY)／米ドル(USD)**のいずれでも表示でき、レートは調整可能
- **制度変更の影響を加味したシナリオ**と**加味しないシナリオ**を分けて比較できる
- 製品単位の予測をSKUへ配分する際は、SKU構成比の**トレンド（変化傾向）**を考慮する
- 経営層向けの**PowerPoint出力**（Power BIからのエクスポート）
- 予測ロジックを口頭で説明するための**トーク原稿（用語解説付き）**は別途Wordファイルとして作成

### 1.2 想定ユーザー
- コマーシャルエクセレンス部門のアナリスト（Excelでパラメータ調整・予測更新）
- 営業企画・マーケティング部門（Power BIダッシュボードで閲覧）
- 経営層（Power BIレポートまたはPowerPointの閲覧）

### 1.3 Streamlit版との関係
本仕様書はStreamlit版（Python + FastAPI + React構成）とは**別系統**の実装である。予測ロジック・データモデル・シナリオ設計の考え方は共通だが、実装手段がExcel+Power BIに最適化されている。両版を並行運用することも、どちらか一方に統一することも可能。

### 1.4 Excel + Power BI構成を選ぶ理由
- 社内のBIツール標準がPower BIである場合、既存の配信・権限管理基盤に乗せられる
- Excelベースなので、Python環境を持たないユーザーでもパラメータ調整・データ更新が可能
- Power BIの階層ドリルダウン・What-ifパラメータ・ウォーターフォールチャートが標準機能として使える

---

## 2. 業界特性に関する前提（ジェネリック/バイオシミラー固有）

（Streamlit版と共通のため、要点のみ記載。詳細はStreamlit版仕様書の2章を参照）

| 特性 | Excel+Power BIでの実現方法 |
|---|---|
| 浸透率S字カーブ | Python in Excel（Microsoft 365 Enterprise環境で利用可能を確認済み）でscipy.optimize.curve_fitを使用。Streamlit版と同一ロジック。Solver+VBAは予備手段として残す |
| 薬価改定イベント | パラメータシートにイベント一覧を管理し、予測数式で条件参照 |
| Sell-in/Sell-outギャップ | 卸別月末在庫データからの実測補正をExcel数式で実装 |
| SKU構成比のトレンド | TREND関数 + 正規化数式でSKU配分比の将来予測を算出 |
| 制度変更の加味/非加味 | シナリオ別の予測結果シートを用意し、Power BIのスライサーで切替 |

---

## 3. データの粒度とマスタ階層

（Streamlit版と完全に共通。4階層構造）

```
疾患領域 (Therapeutic Area)
  └─ 成分 (Ingredient / 一般名)         ← IQVIA市場データ・浸透率はこの単位で集計
       └─ 製品 (Product / 自社製品名)    ← ブランドとしての括り
            └─ SKU (規格・包装単位)      ← 予測の最終出力単位、卸の発注・在庫もこの単位
```

---

## 4. システムアーキテクチャ

### 4.1 全体構成

```
┌──────────────────────────────────────────────────────────────────┐
│                     Excel ワークブック (.xlsm)                    │
│                                                                  │
│  [データ取込層] Power Query                                       │
│    CSV/Excel(IQVIA, Sell-in, Sell-out, 卸別在庫)                 │
│    → テーブル化して各シートに展開                                  │
│                                                                  │
│  [マスタ管理層] テーブル                                          │
│    疾患領域/成分/製品/SKUマスタ、制度イベントマスタ、為替レート      │
│                                                                  │
│  [パラメータ管理層] パラメータシート                               │
│    浸透率上限・速度、薬価改定率、市場成長率、SKUミックス比率、      │
│    競合参入想定、為替レート（全てユーザー編集可能）                 │
│                                                                  │
│  [予測エンジン層] Excel数式 + VBA + Solver                        │
│    Step1: 市場トレンド予測 → FORECAST.ETS                         │
│    Step2: 浸透率予測 → ロジスティック曲線（Solver or Python in Excel）│
│    Step3: 自社シェア予測 → TREND + パラメータ参照                  │
│    Step4: SKU配分 → TREND + 正規化                                │
│    Step5: 統合 → シナリオ別の乗算数式                             │
│                                                                  │
│  [出力層] forecast_results テーブル                                │
│    SKU×月×シナリオの予測結果（Power BIが読み取る）                  │
│                                                                  │
└──────────────┬───────────────────────────────────────────────────┘
               │ Power BIがExcelファイルをデータソースとして接続
               ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Power BI (.pbix)                              │
│                                                                  │
│  [データモデル層]                                                  │
│    Excel各テーブルをインポート/DirectQuery                         │
│    リレーションシップ（スタースキーマ）の定義                       │
│    DAXメジャー（通貨換算、前年比、シナリオ差分等）                  │
│                                                                  │
│  [ダッシュボード層]                                                │
│    ページ1: ポートフォリオ概観                                     │
│    ページ2: 製品/SKU詳細（ドリルダウン）                           │
│    ページ3: シナリオ比較（加味 vs 非加味）                         │
│    ページ4: 浸透率カーブ                                           │
│    ページ5: 要因分解（ウォーターフォール）                         │
│    ページ6: 在庫状況                                               │
│                                                                  │
│  [エクスポート]                                                    │
│    Power BI → PowerPoint（標準エクスポート機能）                    │
│    Power BI → Excel（標準エクスポート機能）                         │
│    Power BI → PDF（標準エクスポート機能）                           │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 ファイル構成

| ファイル | 用途 | 更新頻度 |
|---|---|---|
| `GE_BS_Forecast_Engine.xlsm` | 計算エンジン本体（データ取込・予測計算・パラメータ管理） | 月次（データ更新時） |
| `GE_BS_Dashboard.pbix` | Power BIダッシュボード（可視化・レポーティング） | Excelの更新に連動 |
| `docs/sample_data/` | サンプルCSV群（Streamlit版と共通） | 初回のみ |
| `docs/talk_script_template.docx` | トーク原稿テンプレート（手動更新） | 四半期ごと目安 |

---

## 5. Excelワークブック設計

### 5.1 シート構成

| シート名 | 内容 | 保護 |
|---|---|---|
| **START** | 操作ガイド、データ更新手順、バージョン情報 | 読み取り専用 |
| **PARAM** | 全パラメータの一覧（ユーザー編集用）。セルに入力規則・条件付き書式を設定 | 編集可能 |
| **M_TherapeuticArea** | 疾患領域マスタ（テーブル） | 編集可能 |
| **M_Ingredient** | 成分マスタ（テーブル） | 編集可能 |
| **M_Product** | 製品マスタ（テーブル） | 編集可能 |
| **M_SKU** | SKUマスタ（テーブル） | 編集可能 |
| **M_Events** | 制度イベントマスタ（テーブル、impact_target/impact_parameter/effect_lag_months含む） | 編集可能 |
| **M_FXRate** | 為替レートマスタ（実績＋予測仮定） | 編集可能 |
| **D_IQVIA** | IQVIA市場データ（Power Queryで取込、テーブル） | Power Query更新 |
| **D_SellIn** | 自社Sell-inデータ（Power Queryで取込、テーブル） | Power Query更新 |
| **D_SellOut** | 自社Sell-outデータ（Power Queryで取込、テーブル） | Power Query更新 |
| **D_Inventory** | 卸別月末在庫データ（Power Queryで取込、テーブル） | Power Query更新 |
| **C_MarketForecast** | Step1: 成分別市場トレンド予測（FORECAST.ETS関数） | 数式保護 |
| **C_Penetration** | Step2: 成分別浸透率予測（ロジスティック曲線パラメータ＋予測値） | Solver実行可 |
| **C_ShareForecast** | Step3: 自社製品シェア予測 | 数式保護 |
| **C_SKUMix** | Step4: SKU構成比トレンド予測（TREND＋正規化） | 数式保護 |
| **C_Integrated** | Step5: 統合予測（シナリオ別、SKU×月次） | 数式保護 |
| **OUT_Adjusted** | forecast_results: 制度変更加味シナリオの出力テーブル | 数式保護 |
| **OUT_Excluded** | forecast_results: 制度変更非加味シナリオの出力テーブル | 数式保護 |
| **LOG** | パラメータ変更履歴（VBAで自動記録） | VBA書込のみ |

### 5.2 パラメータシート（PARAM）の設計

| セクション | パラメータ | 入力方法 | デフォルト値の出典 |
|---|---|---|---|
| 薬価 | 次回改定予定月 | 日付入力 | 制度カレンダー |
| 薬価 | 改定率（成分別） | %入力 | 過去改定率の平均 |
| 浸透率 | 浸透率上限L（成分別） | 数値入力（0〜1） | Solverフィッティング結果 |
| 浸透率 | 立ち上がり速度k（成分別） | 数値入力 | Solverフィッティング結果 |
| 浸透率 | 変曲点x0（成分別） | 数値入力 | Solverフィッティング結果 |
| 市場 | 疾患領域市場成長率 | %入力 | IQVIA過去トレンド |
| 競合 | 新規競合参入時期 | 日付入力 | 手動 |
| 競合 | 想定シェア | %入力 | 手動 |
| 在庫 | 適正在庫日数（卸別） | 数値入力 | 実測平均 |
| 在庫 | 改定前積み増し率 | %入力 | 過去実測 |
| 在庫 | 改定後調整率 | %入力 | 過去実測 |
| SKUミックス | SKU構成比トレンド係数 | 数値入力（自動算出値を上書き可） | TREND関数の結果 |
| 通貨 | 予測仮定レート（JPY/USD） | 数値入力 | 直近実績レート |
| シナリオ | 楽観/悲観の調整幅 | %入力 | ±10%をデフォルト |

PARAMシートの各セルには以下を設定する：
- **入力規則**（データの入力規則）：範囲チェック（例：浸透率上限は0〜1）
- **条件付き書式**：デフォルト値から大きく乖離した場合にハイライト
- **セル名**：名前付き範囲を定義し、予測数式から`=PARAM_L_ING01`のように参照（セルアドレス直参照を回避）

### 5.3 変更履歴ログ（LOGシート）

VBA（Worksheet_Change イベント）でPARAMシートへの入力を自動記録する。

| 列 | 内容 |
|---|---|
| timestamp | 変更日時 |
| user | Windowsユーザー名（Application.UserName） |
| sheet | 変更されたシート名 |
| cell_address | 変更されたセル |
| parameter_name | 名前付き範囲名（該当する場合） |
| old_value | 変更前の値 |
| new_value | 変更後の値 |

---

## 6. 予測ロジック（Excel実装）

### 6.1 Step1: 疾患領域・成分市場サイズ予測

| 項目 | 実装方法 |
|---|---|
| 使用関数 | `FORECAST.ETS`（Excel 2016以降の標準関数） |
| 入力 | D_IQVIAシートの成分別月次販売数量（実績） |
| 出力 | C_MarketForecastシートに成分×36ヶ月の市場サイズ予測値 |
| 季節性 | FORECAST.ETSの seasonality パラメータ（12=月次季節性を自動検出）を使用 |
| 信頼区間 | `FORECAST.ETS.CONFINT` 関数で80%/95%信頼区間を算出 |

数式例：
```
=FORECAST.ETS(予測対象月, 実績値の範囲, 実績月の範囲, 12, 1)
```

### 6.2 Step2: ジェネリック/バイオシミラー浸透率予測

浸透率のS字カーブフィッティングには**Python in Excel（推奨）**を使用する。社内環境（Microsoft 365 Apps for enterprise）で利用可能であることを確認済み。

**推奨: Python in Excel**

Microsoft 365のPython in Excel機能で、セル内でscipy.optimizeを直接実行する。Streamlit版と同一のロジスティック曲線フィッティングがExcel上で動く。

```python
=PY(
import numpy as np
from scipy.optimize import curve_fit

def logistic(t, L, k, x0):
    return L / (1 + np.exp(-k * (t - x0)))

# xl()でExcelのデータ範囲を参照
t_data = xl("C_Penetration[month_index]", headers=True)
pen_data = xl("C_Penetration[actual_penetration]", headers=True)

popt, _ = curve_fit(logistic, t_data, pen_data, p0=[0.8, 0.1, 15])
popt  # [L, k, x0] を返す
)
```

| 項目 | 内容 |
|---|---|
| モデル式 | ロジスティック関数: `pen(t) = L / (1 + EXP(-k * (t - x0)))` |
| パラメータ | L（上限）、k（速度）、x0（変曲点）の3つ |
| フィッティング | Python in Excelのセルでscipy.optimize.curve_fitを実行 |
| 操作 | C_Penetrationシートの指定セルにPY関数を入力。再計算で自動フィッティング |
| 制度イベント反映 | M_Eventsシートのimpact_target=penetrationの行を参照し、effect_lag_months後からL, kの値を段階的に変化させる数式を構築 |

**予備手段: Excel Solver + VBA**

Python in ExcelがIT部門によりブロックされている場合等の代替手段。

### 6.3 Step3: 自社製品シェア予測

| 項目 | 実装方法 |
|---|---|
| 使用関数 | `TREND` または線形回帰の数式 |
| 入力 | D_IQVIAの自社製品シェア実績 |
| パラメータ | 新規競合参入時期・想定シェア（PARAMシートから参照） |
| 出力 | C_ShareForecastシートに成分×36ヶ月の自社シェア予測 |

競合参入による不連続な変化は、IF文で参入月以降のシェアを段階的に低下させる数式で対応する。

### 6.4 Step4: SKU配分（トレンド考慮）

| 項目 | 実装方法 |
|---|---|
| 使用関数 | `TREND`（線形トレンド） + 正規化数式 |
| 入力 | D_SellOutから算出した各SKUの過去構成比 |
| 出力 | C_SKUMixシートにSKU×36ヶ月の構成比予測（合計=1に正規化） |

数式例（SKU0101の月tの構成比）：
```
= TREND(過去構成比の範囲, 過去月indexの範囲, t)
```
正規化：
```
= 個別SKUのTREND値 / SUM(同一製品内全SKUのTREND値)
```

トレンドが不自然な値（0未満、1超）を示す場合は、MAX(0, MIN(1, ...))でクリッピングした上で正規化する。

### 6.5 Step5: 統合（シナリオ別）

C_Integratedシートで、Step1〜4の結果とPARAMシートのパラメータを組み合わせて最終予測を算出する。

```
自社販売予測(SKU, 月t, シナリオ)
  = C_MarketForecast(成分, t)                    ← Step1
  × C_Penetration(成分, t, シナリオ)             ← Step2（加味/非加味で浸透率が異なる）
  × C_ShareForecast(成分, t)                     ← Step3
  × C_SKUMix(SKU, t)                             ← Step4
  × IF(シナリオ="加味", 薬価改定係数, 1)          ← 価格系イベント
  ± IF(シナリオ="加味", 在庫変動補正, 0)          ← 在庫系イベント（Sell-in用）
```

OUT_Adjustedシート（加味）とOUT_Excludedシート（非加味）にそれぞれ結果を出力する。楽観/悲観シナリオは、上記数式のパラメータ参照先をPARAMシートの楽観/悲観セクションに切り替えることで実現する（シート複製、または数式内のINDIRECT参照）。

### 6.6 Sell-in / Sell-outの扱い

Streamlit版と同様の考え方をExcel数式で実装する。

- **Sell-out**をベース需要として上記モデルで予測
- **在庫変動の実測**：D_Inventoryの月末在庫から`在庫増減 = 当月Sell-in − 当月Sell-out`を算出
- **在庫日数**：`=月末在庫 / (直近3ヶ月のSell-out平均 / 30)`
- **Sell-in予測**：`=Sell-out予測 + 定常在庫変動 + IF(シナリオ="加味", イベント在庫変動, 0)`

### 6.7 通貨換算

- 全ての計算はJPYベースで実施
- OUT_Adjusted / OUT_Excluded の各行にUSD列を追加
- `=JPY額 / VLOOKUP(月, M_FXRateテーブル, jpy_per_usd列, FALSE)`
- Power BI側ではDAXメジャーで表示通貨の切替を実装

---

## 7. Power BI設計

### 7.1 データモデル（スタースキーマ）

```
               ┌─────────────┐
               │  DIM_Date    │ ← 日付ディメンション（年/四半期/月）
               └──────┬──────┘
                      │
┌───────────┐  ┌──────┴──────┐  ┌───────────────┐
│ DIM_SKU   ├──┤ FACT_Forecast├──┤ DIM_Scenario  │
└─────┬─────┘  └──────┬──────┘  └───────────────┘
      │               │
┌─────┴─────┐  ┌──────┴──────┐
│DIM_Product│  │FACT_Actuals │ ← Sell-in/Sell-out/在庫の実績
└─────┬─────┘  └─────────────┘
      │
┌─────┴────────┐
│DIM_Ingredient│
└─────┬────────┘
      │
┌─────┴──────────────┐
│DIM_TherapeuticArea │
└────────────────────┘
```

| テーブル | ソース | 粒度 |
|---|---|---|
| FACT_Forecast | OUT_Adjusted + OUT_Excluded | SKU × 月 × シナリオ |
| FACT_Actuals | D_SellIn + D_SellOut + D_Inventory | SKU × 月 × (卸 or 施設区分) |
| DIM_Date | Power Queryで自動生成 | 日単位（月/四半期/年でロールアップ） |
| DIM_SKU | M_SKU | SKU単位 |
| DIM_Product | M_Product | 製品単位 |
| DIM_Ingredient | M_Ingredient | 成分単位 |
| DIM_TherapeuticArea | M_TherapeuticArea | 疾患領域単位 |
| DIM_Scenario | シナリオマスタ（adjusted/excluded × base/opt/pess） | シナリオ単位 |
| DIM_FXRate | M_FXRate | 月 × レートタイプ |

### 7.2 主要DAXメジャー

```dax
// 通貨切替メジャー
Sales Amount =
VAR selectedCurrency = SELECTEDVALUE(CurrencySelector[Currency], "JPY")
VAR amountJPY = SUM(FACT_Forecast[sellout_forecast_jpy])
VAR fxRate = LOOKUPVALUE(DIM_FXRate[jpy_per_usd], DIM_FXRate[period], MAX(DIM_Date[YearMonth]))
RETURN
    IF(selectedCurrency = "USD", DIVIDE(amountJPY, fxRate), amountJPY)

// シナリオ差分（制度変更影響額）
Regulatory Impact =
VAR adjusted = CALCULATE(SUM(FACT_Forecast[sellout_forecast_jpy]),
    FACT_Forecast[scenario_axis1] = "adjusted")
VAR excluded = CALCULATE(SUM(FACT_Forecast[sellout_forecast_jpy]),
    FACT_Forecast[scenario_axis1] = "excluded")
RETURN adjusted - excluded

// 前年同月比
YoY Growth =
VAR currentValue = [Sales Amount]
VAR priorValue = CALCULATE([Sales Amount], DATEADD(DIM_Date[Date], -12, MONTH))
RETURN DIVIDE(currentValue - priorValue, priorValue)

// 浸透率（Power BI上で参照する場合）
Penetration Rate =
DIVIDE(
    CALCULATE(SUM(FACT_Actuals[sales_units]), FACT_Actuals[manufacturer_type] <> "オリジナル"),
    SUM(FACT_Actuals[sales_units])
)
```

### 7.3 ダッシュボード ページ構成

| ページ | 内容 | 主要ビジュアル |
|---|---|---|
| 1. ポートフォリオ概観 | 全体KPI、成分別サマリー、月次予測（積み上げ） | カード、テーブル、積み上げ棒グラフ |
| 2. 製品/SKU詳細 | 成分→製品→SKUのドリルダウン、36ヶ月予測 | 折れ線（実績+予測）、ドリルダウン階層 |
| 3. 浸透率カーブ | 成分別S字カーブ（実績+予測）、加味/非加味比較 | 折れ線（2系列重ね） |
| 4. シナリオ比較 | 加味 vs 非加味、差分＝影響額の表示 | クラスター棒グラフ、テーブル |
| 5. 要因分解 | 前年比の変化を市場成長/浸透率/薬価/その他に分解 | ウォーターフォール（Power BI標準） |
| 6. 在庫状況 | 卸別在庫日数推移、Sell-in/Sell-outギャップ | 折れ線 + 帯グラフ |

### 7.4 スライサー・フィルター

全ページ共通で以下のスライサーを配置する：

| スライサー | 内容 |
|---|---|
| 疾患領域 | ドロップダウン（全選択可） |
| 成分 | ドロップダウン（疾患領域に連動） |
| 製品 / SKU | ドロップダウン（成分に連動） |
| シナリオ軸1 | ボタン式（加味 / 非加味） |
| シナリオ軸2 | ボタン式（ベース / 楽観 / 悲観） |
| 通貨 | ボタン式（JPY / USD） |
| 期間 | スライダー（年月の範囲選択） |

### 7.5 What-ifパラメータ（Power BI）

Power BIの「What-if パラメータ」機能を使い、ダッシュボード上で以下をスライダー操作できるようにする。

| パラメータ | 範囲 | 用途 |
|---|---|---|
| 為替レート（JPY/USD） | 100〜200（ステップ1） | 為替感度のリアルタイム確認 |
| 市場成長率の調整 | -5%〜+5%（ステップ0.5%） | トレンドの強弱を即座に確認 |

ただし、浸透率パラメータ等のより複雑な調整はExcel側のPARAMシートで行い、Power BIのデータ更新で反映する運用とする。

### 7.6 エクスポート

| 出力 | 方法 |
|---|---|
| PowerPoint | Power BI Desktop → 「ファイル」→「PowerPointにエクスポート」（各ページがスライドになる） |
| PDF | Power BI Desktop → 「ファイル」→「PDFにエクスポート」 |
| Excel | Power BI Service → レポート右上「エクスポート」→「Excelにエクスポート」（ビジュアルのデータを取得） |
| トーク原稿 | 別途Wordテンプレートに予測数値を手動転記、またはVBAマクロで自動生成 |

---

## 8. シナリオ設計

（Streamlit版と同じ2軸構造。Excel+Power BIでの実現方法のみ異なる）

### 8.1 軸1：制度変更影響の加味（Adjusted）／非加味（Excluded）

- Excel側：OUT_Adjusted / OUT_Excluded の2シートに別々に予測結果を出力
- Power BI側：FACT_Forecastテーブルにscenario_axis1列を持たせ、スライサーで切替

### 8.2 軸2：ベース／楽観／悲観

- Excel側：PARAMシートに「ベース」「楽観」「悲観」の3セクションを持ち、C_Integratedの数式でINDIRECT参照先を切り替える
- Power BI側：scenario_axis2列でスライサー切替

---

## 9. 運用フロー

### 9.1 月次更新手順

```
1. CSVデータの準備
   IQVIA/Sell-in/Sell-out/卸別在庫の最新月データをCSV形式で取得

2. Excelへの取込
   GE_BS_Forecast_Engine.xlsm を開く
   → [データ] → [すべて更新]（Power Queryが各CSVを自動取込）

3. パラメータ確認・調整（必要な場合のみ）
   PARAMシートの値を確認。薬価改定や新規競合等の変更があれば更新
   → 浸透率の再フィッティングが必要な場合は「フィッティング実行」ボタンをクリック

4. 予測の再計算
   [数式] → [ブックの計算]（Ctrl+Alt+F9）で全数式を再計算
   → OUT_Adjusted / OUT_Excluded が更新される

5. Power BIの更新
   GE_BS_Dashboard.pbix を開く
   → [ホーム] → [更新]（Excelファイルから最新データを読み込み）

6. レビュー・レポーティング
   Power BIダッシュボードで予測結果を確認
   → 必要に応じてPowerPoint/PDF/Excelにエクスポート
```

### 9.2 Power BI Service での共有（オプション）

社内のPower BI Service環境がある場合は、以下の共有方法が使える。

| 方法 | 内容 |
|---|---|
| ワークスペース共有 | 特定のチームメンバーに閲覧/編集権限を付与 |
| アプリとして公開 | 読み取り専用のアプリとして社内に配布 |
| スケジュール更新 | Excelファイルを共有ドライブに置き、定時自動更新を設定 |
| Row-Level Security | ユーザーごとに閲覧可能な疾患領域/製品を制限（必要な場合） |

---

## 10. 非機能要件

| 項目 | 要件 |
|---|---|
| パフォーマンス | SKU数百件規模でも、Excel再計算は30秒以内。Power BIの表示はインタラクティブ（数秒以内） |
| データ保護 | 自社販売データを含むExcelファイルは社内ネットワーク内にのみ保管。Power BI Serviceへのアップロードは社内テナントに限定 |
| 拡張性 | マスタテーブルへの行追加でSKU/成分/疾患領域を追加可能（数式はテーブル参照で自動拡張） |
| 監査性 | LOGシートでパラメータ変更履歴を保持 |
| 互換性 | Microsoft 365 Apps for enterprise（確認済み）。Python in Excel利用可能。バージョン 2605（ビルド 20026.20166）以降 |

---

## 11. 開発ステップ（推奨マイルストーン）

### Phase 1: Excelワークブック構築

| Step | 内容 | 目安期間 |
|---|---|---|
| 1-1 | シート構造・マスタテーブルの作成、Power QueryによるCSV取込設定 | 1日 |
| 1-2 | Step1（市場トレンド予測、FORECAST.ETS）の実装・検証 | 1日 |
| 1-3 | Step2（浸透率S字カーブ、Python in Excelでcurve_fit）の実装・検証 | 1日 |
| 1-4 | Step3〜4（自社シェア予測、SKU配分トレンド）の実装・検証 | 1日 |
| 1-5 | Step5（統合予測、シナリオ別出力）の実装・検証 | 1日 |
| 1-6 | PARAMシートのUI整備（入力規則・条件付き書式・名前付き範囲）、LOGのVBA実装 | 1日 |

### Phase 2: Power BIダッシュボード構築

| Step | 内容 | 目安期間 |
|---|---|---|
| 2-1 | データモデル構築（Excel接続、リレーションシップ、DAXメジャー） | 1日 |
| 2-2 | ポートフォリオ概観・製品詳細ページの作成 | 1日 |
| 2-3 | 浸透率カーブ・シナリオ比較ページの作成 | 1日 |
| 2-4 | 要因分解（ウォーターフォール）・在庫状況ページの作成 | 1日 |
| 2-5 | スライサー・What-ifパラメータの設定、エクスポート確認 | 0.5日 |

### Phase 3: 運用化

| Step | 内容 | 目安期間 |
|---|---|---|
| 3-1 | 実データでの検証・パラメータ初期値のフィッティング | 2日 |
| 3-2 | Power BI Service への発行・共有設定（オプション） | 0.5日 |
| 3-3 | 月次運用フローの確立・ユーザーガイド作成 | 1日 |

---

## 12. Streamlit版との機能差分

| 機能 | Streamlit版 | Excel+Power BI版 |
|---|---|---|
| 浸透率自動フィッティング | scipy.optimize（自動） | Python in Excel（同一ロジック）/ Solver+VBA（予備） |
| ダッシュボード | Streamlit（カスタムUI） | Power BI（標準ビジュアル、ドリルダウンが強力） |
| 階層ドリルダウン | サイドバー選択 | Power BI標準機能（クリックで疾患領域→成分→製品→SKU） |
| パラメータ調整 | Webスライダー（即時反映） | Excelセル入力（再計算必要） |
| 通貨切替 | 画面トグル | Power BIスライサー or What-ifパラメータ |
| PowerPoint出力 | python-pptx（自動生成） | Power BI標準エクスポート |
| トーク原稿（Word） | python-docx（自動生成） | Wordテンプレートに手動転記 or VBAマクロ |
| パラメータ変更履歴 | DB保存 | VBA+LOGシート |
| デプロイ・共有 | Streamlit Cloud（URL共有） | Power BI Service（社内テナント） or ファイル共有 |
| Python環境の要否 | 必須 | 不要（Python in Excel使用時のみMicrosoft 365必要） |

---

## 13. 未確定事項・要確認ポイント

- Excel Solver の利用可否（社内PCのExcelバージョン・Solverアドインの有効化状況）
- Python in Excel の利用可否（Microsoft 365ライセンスの有無、IT部門の承認状況）
- Power BI Desktop / Service のライセンス状況（Pro / Premium Per User / Premium Per Capacity）
- Power BI Service のワークスペース・共有設定の社内ルール
- Excelファイルの保管場所（SharePoint / OneDrive / 社内ファイルサーバー）→ Power BIの接続方法に影響
- 実データのCSV出力経路（既存のAlteryx ワークフローから出力する場合、出力先フォルダをPower Queryのソースパスに合わせる）
- IQVIAデータの実際のフォーマット（Streamlit版と共通の確認事項）

---

*本仕様書はExcel + Power BI構成での実装用ドラフトです。Streamlit版の仕様書・サンプルデータと併せて参照し、Phase 1のExcelワークブック構築から着手することを推奨します。*

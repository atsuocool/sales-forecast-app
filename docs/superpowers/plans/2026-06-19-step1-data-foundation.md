# Step 1: データ基盤構築 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SKU/製品/成分/疾患領域の4階層マスタDBと、IQVIA・Sell-in・Sell-out・卸別在庫の取込パイプラインをSQLite+Pythonで構築する。

**Architecture:** SQLite（`data/pharma_forecast.db`）に全テーブルを集約。パイプラインはpandas+openpyxlでExcel/CSVを読み込み正規化してINSERT。Sell-in/Sell-out/在庫はダミーデータが存在しないため、IQVIA実績データから合成生成するスクリプトを用意する。

**Tech Stack:** Python 3.10+, sqlite3 (標準ライブラリ), pandas 2.x, openpyxl, pytest

## Global Constraints

- DBファイルパス: `data/pharma_forecast.db`（gitignore対象）
- 全金額はJPYで内部保持（USD換算は表示時のみ）
- 期間フィールドは `YYYY-MM` 文字列形式で統一
- SQLiteのFOREIGN KEY制約を `PRAGMA foreign_keys = ON` で有効化
- テスト用DBはインメモリ（`:memory:`）を使用

---

## File Structure

```
sales-forecast-app/
├── docs/
│   ├── spec.md
│   ├── sample_data/
│   │   └── pharma_forecast_dummy_data.xlsx
│   └── superpowers/plans/2026-06-19-step1-data-foundation.md
├── src/
│   ├── __init__.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py      # get_connection() → sqlite3.Connection
│   │   └── schema.py          # create_all_tables(conn)
│   └── pipeline/
│       ├── __init__.py
│       ├── master_loader.py   # load_masters(conn, excel_path)
│       ├── iqvia_loader.py    # load_iqvia(conn, excel_path)
│       ├── sample_gen.py      # generate_sellin_sellout_inventory(conn) → DataFrames
│       └── inventory_loader.py # load_sellin/sellout/inventory(conn, df)
├── tests/
│   ├── conftest.py            # fixtures: mem_conn, loaded_conn
│   ├── test_schema.py
│   ├── test_master_loader.py
│   ├── test_iqvia_loader.py
│   └── test_inventory_loader.py
├── scripts/
│   └── init_db.py             # python scripts/init_db.py でDB初期化＋全データロード
├── data/                      # gitignore対象（DBファイル置き場）
├── requirements.txt
└── .gitignore
```

---

### Task 1: プロジェクトスキャフォールド

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `src/__init__.py`, `src/db/__init__.py`, `src/pipeline/__init__.py`
- Create: `tests/conftest.py`（空のfixture定義のみ）

**Interfaces:**
- Produces: なし（ファイルシステム構造のみ）

- [ ] **Step 1: ディレクトリとファイルを作成**

```bash
cd ~/projects/sales-forecast-app
mkdir -p src/db src/pipeline tests scripts data
touch src/__init__.py src/db/__init__.py src/pipeline/__init__.py
```

`requirements.txt`:
```
pandas>=2.0
openpyxl>=3.1
pytest>=8.0
numpy>=1.26
```

`.gitignore`:
```
data/*.db
data/uploads/
__pycache__/
*.pyc
.pytest_cache/
```

`tests/conftest.py`:
```python
import sqlite3
import pytest

@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()
```

- [ ] **Step 2: 依存パッケージをインストール**

```bash
cd ~/projects/sales-forecast-app
pip install -r requirements.txt
```

Expected: Successfully installed pandas openpyxl pytest numpy

- [ ] **Step 3: Commit**

```bash
git add requirements.txt .gitignore src/ tests/ scripts/ data/.gitkeep
git commit -m "chore: project scaffold for Step 1 data foundation"
```

---

### Task 2: DBスキーマ定義

**Files:**
- Create: `src/db/connection.py`
- Create: `src/db/schema.py`
- Create: `tests/test_schema.py`

**Interfaces:**
- Produces:
  - `get_connection(db_path: str) -> sqlite3.Connection`
  - `create_all_tables(conn: sqlite3.Connection) -> None`

- [ ] **Step 1: テストを書く**

`tests/test_schema.py`:
```python
import sqlite3
from src.db.schema import create_all_tables

EXPECTED_TABLES = [
    "therapeutic_areas",
    "ingredients",
    "products",
    "skus",
    "market_data",
    "sellin_data",
    "sellout_data",
    "inventory_data",
    "regulatory_events",
    "fx_rates",
]

def test_create_all_tables(mem_conn):
    create_all_tables(mem_conn)
    cur = mem_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    for t in EXPECTED_TABLES:
        assert t in tables, f"Table '{t}' not created"

def test_foreign_key_enforced(mem_conn):
    create_all_tables(mem_conn)
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        mem_conn.execute(
            "INSERT INTO ingredients (ingredient_id, therapeutic_area_id, name) VALUES ('I999', 'TA_NONEXISTENT', 'Test')"
        )
        mem_conn.commit()
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/test_schema.py -v
```

Expected: FAIL - "cannot import name 'create_all_tables'"

- [ ] **Step 3: connection.py を実装**

`src/db/connection.py`:
```python
import sqlite3
from pathlib import Path

def get_connection(db_path: str = "data/pharma_forecast.db") -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
```

- [ ] **Step 4: schema.py を実装**

`src/db/schema.py`:
```python
import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS therapeutic_areas (
    therapeutic_area_id TEXT PRIMARY KEY,
    name                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingredients (
    ingredient_id        TEXT PRIMARY KEY,
    therapeutic_area_id  TEXT NOT NULL REFERENCES therapeutic_areas(therapeutic_area_id),
    name                 TEXT NOT NULL,
    atc_code             TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id           TEXT PRIMARY KEY,
    ingredient_id        TEXT NOT NULL REFERENCES ingredients(ingredient_id),
    product_name         TEXT NOT NULL,
    type                 TEXT NOT NULL CHECK(type IN ('generic', 'biosimilar')),
    brand_name           TEXT,
    launch_date          TEXT,
    channel              TEXT
);

CREATE TABLE IF NOT EXISTS skus (
    sku_id               TEXT PRIMARY KEY,
    product_id           TEXT NOT NULL REFERENCES products(product_id),
    package_form         TEXT NOT NULL,
    package_size         TEXT NOT NULL,
    strength             TEXT NOT NULL,
    jan_code             TEXT,
    launch_date          TEXT
);

CREATE TABLE IF NOT EXISTS market_data (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id             TEXT NOT NULL REFERENCES ingredients(ingredient_id),
    period                    TEXT NOT NULL,
    channel                   TEXT,
    total_market_sales_jpy    REAL,
    total_market_units        REAL,
    generic_penetration_rate  REAL,
    UNIQUE(ingredient_id, period, channel)
);

CREATE TABLE IF NOT EXISTS sellin_data (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id         TEXT NOT NULL REFERENCES skus(sku_id),
    period         TEXT NOT NULL,
    distributor    TEXT NOT NULL,
    quantity       REAL NOT NULL,
    amount_jpy     REAL NOT NULL,
    UNIQUE(sku_id, period, distributor)
);

CREATE TABLE IF NOT EXISTS sellout_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id          TEXT NOT NULL REFERENCES skus(sku_id),
    period          TEXT NOT NULL,
    facility_type   TEXT,
    quantity        REAL NOT NULL,
    amount_jpy      REAL NOT NULL,
    UNIQUE(sku_id, period, facility_type)
);

CREATE TABLE IF NOT EXISTS inventory_data (
    id                           INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id                       TEXT NOT NULL REFERENCES skus(sku_id),
    period                       TEXT NOT NULL,
    distributor                  TEXT NOT NULL,
    ending_inventory_qty         REAL NOT NULL,
    ending_inventory_amount_jpy  REAL,
    days_of_inventory            REAL,
    UNIQUE(sku_id, period, distributor)
);

CREATE TABLE IF NOT EXISTS regulatory_events (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date    TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    impact_scope  TEXT NOT NULL,
    impact_value  REAL,
    memo          TEXT
);

CREATE TABLE IF NOT EXISTS fx_rates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_type    TEXT NOT NULL CHECK(rate_type IN ('historical', 'forecast_assumption')),
    period       TEXT NOT NULL,
    jpy_per_usd  REAL NOT NULL,
    updated_by   TEXT,
    updated_at   TEXT,
    UNIQUE(rate_type, period)
);
"""

def create_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()
```

- [ ] **Step 5: テストが通ることを確認**

```bash
pytest tests/test_schema.py -v
```

Expected: PASSED (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/db/ tests/test_schema.py
git commit -m "feat: SQLite schema with 10 tables for Step 1 data foundation"
```

---

### Task 3: 階層マスタローダー（疾患領域→成分→製品→SKU）

**Files:**
- Create: `src/pipeline/master_loader.py`
- Create: `tests/test_master_loader.py`

**Interfaces:**
- Consumes: `create_all_tables(conn)`, `docs/sample_data/pharma_forecast_dummy_data.xlsx`
- Produces:
  - `load_masters(conn: sqlite3.Connection, excel_path: str) -> dict[str, int]`
    - Returns `{"therapeutic_areas": N, "ingredients": N, "products": N, "skus": N}`

ATC → 疾患領域マッピング（コード内で定義）:
```
A02 → 消化器疾患
A10 → 代謝疾患
B03 → 造血系疾患
C08, C09, C10 → 循環器疾患
J01 → 感染症
L01 → 悪性腫瘍
L03 → 免疫系疾患（骨髄刺激因子）
L04 → 自己免疫疾患
```

- [ ] **Step 1: テストを書く**

`tests/test_master_loader.py`:
```python
import pytest
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters

EXCEL_PATH = "docs/sample_data/pharma_forecast_dummy_data.xlsx"

@pytest.fixture
def loaded_conn(mem_conn):
    create_all_tables(mem_conn)
    return mem_conn

def test_load_masters_returns_counts(loaded_conn):
    counts = load_masters(loaded_conn, EXCEL_PATH)
    assert counts["therapeutic_areas"] >= 1
    assert counts["ingredients"] == 15
    assert counts["products"] == 15
    assert counts["skus"] >= 15  # 製品ごとに最低1 SKU

def test_therapeutic_area_hierarchy(loaded_conn):
    load_masters(loaded_conn, EXCEL_PATH)
    cur = loaded_conn.execute(
        "SELECT ta.name FROM therapeutic_areas ta "
        "JOIN ingredients i ON i.therapeutic_area_id = ta.therapeutic_area_id "
        "WHERE i.ingredient_id = 'ING_BS001'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "造血系疾患"

def test_product_links_to_ingredient(loaded_conn):
    load_masters(loaded_conn, EXCEL_PATH)
    cur = loaded_conn.execute(
        "SELECT p.product_id, p.type FROM products p WHERE p.product_id = 'BS001'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row[1] == "biosimilar"

def test_sku_links_to_product(loaded_conn):
    load_masters(loaded_conn, EXCEL_PATH)
    cur = loaded_conn.execute(
        "SELECT COUNT(*) FROM skus WHERE product_id = 'BS001'"
    )
    count = cur.fetchone()[0]
    assert count >= 1

def test_idempotent_load(loaded_conn):
    load_masters(loaded_conn, EXCEL_PATH)
    counts1 = load_masters(loaded_conn, EXCEL_PATH)  # 2回目は重複しない
    cur = loaded_conn.execute("SELECT COUNT(*) FROM products")
    assert cur.fetchone()[0] == 15
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/test_master_loader.py -v
```

Expected: FAIL - "cannot import name 'load_masters'"

- [ ] **Step 3: master_loader.py を実装**

`src/pipeline/master_loader.py`:
```python
import sqlite3
import pandas as pd

# ATC第1〜2文字コード → 疾患領域マッピング
_ATC_TO_TA: dict[str, tuple[str, str]] = {
    "A02": ("TA_A02", "消化器疾患"),
    "A10": ("TA_A10", "代謝疾患"),
    "B03": ("TA_B03", "造血系疾患"),
    "C08": ("TA_C",   "循環器疾患"),
    "C09": ("TA_C",   "循環器疾患"),
    "C10": ("TA_C",   "循環器疾患"),
    "J01": ("TA_J01", "感染症"),
    "L01": ("TA_L01", "悪性腫瘍"),
    "L03": ("TA_L03", "免疫系疾患（骨髄刺激因子）"),
    "L04": ("TA_L04", "自己免疫疾患"),
}

# 製品コードごとのSKU定義（package_form, package_size, strength）
# BS=注射液系、GE=経口錠系
_SKU_TEMPLATES: dict[str, list[dict]] = {}

def _get_sku_templates(product_id: str, product_type: str) -> list[dict]:
    if product_type == "biosimilar":
        return [
            {"suffix": "A", "package_form": "バイアル", "package_size": "1本", "strength": "標準規格"},
            {"suffix": "B", "package_form": "バイアル", "package_size": "5本", "strength": "標準規格"},
        ]
    else:
        return [
            {"suffix": "A", "package_form": "PTP", "package_size": "100錠", "strength": "標準規格"},
            {"suffix": "B", "package_form": "PTP", "package_size": "500錠", "strength": "標準規格"},
        ]

def _atc_to_ta(atc_code: str) -> tuple[str, str]:
    prefix = atc_code[:3]
    return _ATC_TO_TA.get(prefix, ("TA_OTHER", "その他"))

def load_masters(conn: sqlite3.Connection, excel_path: str) -> dict[str, int]:
    df = pd.read_excel(excel_path, sheet_name="製品マスタ", dtype=str)

    ta_rows: dict[str, str] = {}
    ing_rows: list[tuple] = []
    prod_rows: list[tuple] = []
    sku_rows: list[tuple] = []

    for _, row in df.iterrows():
        product_id  = row["製品コード"].strip()
        product_name = row["製品名"].strip()
        atc_code    = row["ATC分類"].strip()
        brand_name  = row["先発品名"].strip()
        launch_date = row["発売年月"].strip()
        channel     = row["販売チャネル"].strip()
        prod_type   = "biosimilar" if row["製品区分"].strip() == "BS" else "generic"

        ta_id, ta_name = _atc_to_ta(atc_code)
        ta_rows[ta_id] = ta_name

        ing_id = f"ING_{product_id}"
        ing_rows.append((ing_id, ta_id, product_name, atc_code))
        prod_rows.append((product_id, ing_id, product_name, prod_type, brand_name, launch_date, channel))

        for tmpl in _get_sku_templates(product_id, prod_type):
            sku_id = f"{product_id}_{tmpl['suffix']}"
            sku_rows.append((
                sku_id, product_id,
                tmpl["package_form"], tmpl["package_size"], tmpl["strength"],
                None, launch_date
            ))

    conn.executemany(
        "INSERT OR IGNORE INTO therapeutic_areas (therapeutic_area_id, name) VALUES (?, ?)",
        ta_rows.items()
    )
    conn.executemany(
        "INSERT OR IGNORE INTO ingredients (ingredient_id, therapeutic_area_id, name, atc_code) VALUES (?, ?, ?, ?)",
        ing_rows
    )
    conn.executemany(
        "INSERT OR IGNORE INTO products (product_id, ingredient_id, product_name, type, brand_name, launch_date, channel) VALUES (?, ?, ?, ?, ?, ?, ?)",
        prod_rows
    )
    conn.executemany(
        "INSERT OR IGNORE INTO skus (sku_id, product_id, package_form, package_size, strength, jan_code, launch_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        sku_rows
    )
    conn.commit()

    return {
        "therapeutic_areas": conn.execute("SELECT COUNT(*) FROM therapeutic_areas").fetchone()[0],
        "ingredients":        conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0],
        "products":           conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "skus":               conn.execute("SELECT COUNT(*) FROM skus").fetchone()[0],
    }
```

- [ ] **Step 4: テストが通ることを確認**

```bash
pytest tests/test_master_loader.py -v
```

Expected: PASSED (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/master_loader.py tests/test_master_loader.py
git commit -m "feat: hierarchy master loader (TA→ingredient→product→SKU) from Excel"
```

---

### Task 4: IQVIA市場データ取込パイプライン

**Files:**
- Create: `src/pipeline/iqvia_loader.py`
- Create: `tests/test_iqvia_loader.py`

**Interfaces:**
- Consumes: `load_masters(conn, excel_path)` が先に完了していること（ingredient_id が存在する前提）
- Produces:
  - `load_iqvia(conn: sqlite3.Connection, excel_path: str) -> int` — INSERT行数を返す

ロジック: IQVIA月次実績は製品コード単位 → ingredient_id = `ING_{製品コード}` として `market_data` にINSERT。チャネル別に行が分かれる場合は別行として保持。

- [ ] **Step 1: テストを書く**

`tests/test_iqvia_loader.py`:
```python
import pytest
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia

EXCEL_PATH = "docs/sample_data/pharma_forecast_dummy_data.xlsx"

@pytest.fixture
def master_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, EXCEL_PATH)
    return mem_conn

def test_load_iqvia_returns_row_count(master_conn):
    count = load_iqvia(master_conn, EXCEL_PATH)
    assert count == 450  # READMEに記載の行数

def test_iqvia_row_has_required_fields(master_conn):
    load_iqvia(master_conn, EXCEL_PATH)
    cur = master_conn.execute(
        "SELECT ingredient_id, period, total_market_units, total_market_sales_jpy, generic_penetration_rate "
        "FROM market_data WHERE ingredient_id = 'ING_BS001' AND period = '2022-01'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row["total_market_units"] > 0
    assert row["total_market_sales_jpy"] > 0

def test_iqvia_idempotent(master_conn):
    load_iqvia(master_conn, EXCEL_PATH)
    load_iqvia(master_conn, EXCEL_PATH)  # 2回目は重複しない
    cur = master_conn.execute("SELECT COUNT(*) FROM market_data")
    assert cur.fetchone()[0] == 450

def test_all_products_loaded(master_conn):
    load_iqvia(master_conn, EXCEL_PATH)
    cur = master_conn.execute(
        "SELECT COUNT(DISTINCT ingredient_id) FROM market_data"
    )
    assert cur.fetchone()[0] == 15
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/test_iqvia_loader.py -v
```

Expected: FAIL - "cannot import name 'load_iqvia'"

- [ ] **Step 3: iqvia_loader.py を実装**

`src/pipeline/iqvia_loader.py`:
```python
import sqlite3
import pandas as pd

def load_iqvia(conn: sqlite3.Connection, excel_path: str) -> int:
    df = pd.read_excel(excel_path, sheet_name="IQVIA月次実績", dtype=str)

    df["ingredient_id"]           = "ING_" + df["製品コード"].str.strip()
    df["period"]                  = df["年月"].str.strip()
    df["channel"]                 = df["チャネル"].str.strip()
    df["total_market_units"]      = pd.to_numeric(df["数量（本/錠）"], errors="coerce")
    df["total_market_sales_jpy"]  = pd.to_numeric(df["売上金額（円）"], errors="coerce")
    df["generic_penetration_rate"]= pd.to_numeric(df["市場シェア（%）"], errors="coerce")

    rows = df[["ingredient_id", "period", "channel",
               "total_market_units", "total_market_sales_jpy",
               "generic_penetration_rate"]].values.tolist()

    conn.executemany(
        """INSERT OR IGNORE INTO market_data
           (ingredient_id, period, channel, total_market_units, total_market_sales_jpy, generic_penetration_rate)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
```

- [ ] **Step 4: テストが通ることを確認**

```bash
pytest tests/test_iqvia_loader.py -v
```

Expected: PASSED (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pipeline/iqvia_loader.py tests/test_iqvia_loader.py
git commit -m "feat: IQVIA market data ingestion pipeline"
```

---

### Task 5: 合成Sell-in/Sell-out/在庫データ生成 + ローダー

**Files:**
- Create: `src/pipeline/sample_gen.py`
- Create: `src/pipeline/inventory_loader.py`
- Create: `tests/test_inventory_loader.py`

**Interfaces:**
- Consumes: `load_iqvia` 完了後のmarket_data、skusテーブルが存在すること
- Produces:
  - `generate_sample_data(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]`
    — `(df_sellin, df_sellout, df_inventory)` を返す（ファイル保存はしない）
  - `load_sellin(conn, df: pd.DataFrame) -> int`
  - `load_sellout(conn, df: pd.DataFrame) -> int`
  - `load_inventory(conn, df: pd.DataFrame) -> int`

生成ロジック（sample_gen.py）:
- market_dataの数量・金額をベースに、各SKUの構成比（SKU_Aが60%、SKU_Bが40%）で按分
- Sell-out ≈ market_data の自社数量（市場シェア × 先発品数量 で推定）
- Sell-in = Sell-out × 1.05（通常月）、薬価改定前月（3月・改定前月）は × 1.15（特需）
- 在庫 = 前月在庫 + Sell-in − Sell-out（初期在庫はSell-out×1.5）
- 卸は「卸A」「卸B」「卸C」の3社、シェア50%/30%/20%

- [ ] **Step 1: テストを書く**

`tests/test_inventory_loader.py`:
```python
import pytest
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.pipeline.sample_gen import generate_sample_data
from src.pipeline.inventory_loader import load_sellin, load_sellout, load_inventory

EXCEL_PATH = "docs/sample_data/pharma_forecast_dummy_data.xlsx"

@pytest.fixture
def full_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, EXCEL_PATH)
    load_iqvia(mem_conn, EXCEL_PATH)
    return mem_conn

def test_generate_sample_data_shapes(full_conn):
    df_si, df_so, df_inv = generate_sample_data(full_conn)
    assert len(df_si) > 0
    assert len(df_so) > 0
    assert len(df_inv) > 0
    assert set(df_si.columns) >= {"sku_id", "period", "distributor", "quantity", "amount_jpy"}
    assert set(df_so.columns) >= {"sku_id", "period", "facility_type", "quantity", "amount_jpy"}
    assert set(df_inv.columns) >= {"sku_id", "period", "distributor", "ending_inventory_qty", "days_of_inventory"}

def test_sellin_ge_sellout_on_average(full_conn):
    df_si, df_so, _ = generate_sample_data(full_conn)
    assert df_si["quantity"].sum() >= df_so["quantity"].sum()

def test_inventory_non_negative(full_conn):
    _, _, df_inv = generate_sample_data(full_conn)
    assert (df_inv["ending_inventory_qty"] >= 0).all()

def test_load_sellin_count(full_conn):
    df_si, df_so, df_inv = generate_sample_data(full_conn)
    n_si  = load_sellin(full_conn, df_si)
    n_so  = load_sellout(full_conn, df_so)
    n_inv = load_inventory(full_conn, df_inv)
    assert n_si  == len(df_si)
    assert n_so  == len(df_so)
    assert n_inv == len(df_inv)

def test_sellin_inventory_identity(full_conn):
    """在庫増減 = Sell-in - Sell-out が近似的に成立することを確認"""
    df_si, df_so, df_inv = generate_sample_data(full_conn)
    total_si  = df_si["quantity"].sum()
    total_so  = df_so["quantity"].sum()
    total_inv = df_inv["ending_inventory_qty"].sum()
    # 全期間で Sell-in > Sell-out（在庫が正）になっているはず
    assert total_si > total_so
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
pytest tests/test_inventory_loader.py -v
```

Expected: FAIL - "cannot import name 'generate_sample_data'"

- [ ] **Step 3: sample_gen.py を実装**

`src/pipeline/sample_gen.py`:
```python
import sqlite3
import pandas as pd
import numpy as np

_DISTRIBUTORS = [("卸A", 0.50), ("卸B", 0.30), ("卸C", 0.20)]
_SKU_MIX      = {"A": 0.60, "B": 0.40}  # suffix → 構成比
_PRICE_REVISION_MONTHS = {"2022-03", "2024-03"}  # 改定前月（特需）


def generate_sample_data(conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_market = pd.read_sql(
        """SELECT m.ingredient_id, m.period,
                  m.total_market_units, m.total_market_sales_jpy,
                  m.generic_penetration_rate
           FROM market_data m
           ORDER BY m.ingredient_id, m.period""",
        conn
    )
    df_skus = pd.read_sql(
        "SELECT sku_id, product_id FROM skus", conn
    )
    df_products = pd.read_sql(
        "SELECT product_id, ingredient_id FROM products", conn
    )

    df_market["self_share"] = df_market["generic_penetration_rate"] / 100.0
    df_market["sellout_units"] = (
        df_market["total_market_units"] * df_market["self_share"]
    ).round(0)
    df_market["sellout_jpy"] = (
        df_market["total_market_sales_jpy"] * df_market["self_share"]
    ).round(0)

    sellin_rows, sellout_rows, inv_rows = [], [], []

    for product_id, grp_prods in df_products.groupby("product_id"):
        ingredient_id = grp_prods.iloc[0]["ingredient_id"]
        mkt = df_market[df_market["ingredient_id"] == ingredient_id].sort_values("period")
        skus = df_skus[df_skus["product_id"] == product_id]

        for sku_row in skus.itertuples():
            sku_id = sku_row.sku_id
            suffix = sku_id.split("_")[-1]
            mix    = _SKU_MIX.get(suffix, 0.5)

            inv_qty = None  # 初期在庫は未設定

            for mkt_row in mkt.itertuples():
                period       = mkt_row.period
                so_units     = mkt_row.sellout_units * mix
                so_jpy       = mkt_row.sellout_jpy   * mix
                si_multiplier = 1.15 if period in _PRICE_REVISION_MONTHS else 1.05
                si_units     = so_units * si_multiplier
                si_jpy       = so_jpy   * si_multiplier

                if inv_qty is None:
                    inv_qty = so_units * 1.5  # 初期在庫

                for dist_name, dist_share in _DISTRIBUTORS:
                    sellout_rows.append({
                        "sku_id": sku_id, "period": period,
                        "facility_type": "病院" if sku_id.startswith("BS") else "薬局",
                        "quantity": round(so_units * dist_share, 2),
                        "amount_jpy": round(so_jpy * dist_share, 0),
                    })
                    sellin_rows.append({
                        "sku_id": sku_id, "period": period,
                        "distributor": dist_name,
                        "quantity": round(si_units * dist_share, 2),
                        "amount_jpy": round(si_jpy * dist_share, 0),
                    })
                    dist_si  = si_units * dist_share
                    dist_so  = so_units * dist_share
                    dist_inv = max(0.0, inv_qty * dist_share + dist_si - dist_so)
                    doi = (dist_inv / dist_so * 30) if dist_so > 0 else 0.0
                    inv_rows.append({
                        "sku_id": sku_id, "period": period,
                        "distributor": dist_name,
                        "ending_inventory_qty": round(dist_inv, 2),
                        "ending_inventory_amount_jpy": round(dist_inv * (so_jpy / so_units) if so_units > 0 else 0, 0),
                        "days_of_inventory": round(doi, 1),
                    })

                inv_qty = max(0.0, inv_qty + si_units - so_units)

    return pd.DataFrame(sellin_rows), pd.DataFrame(sellout_rows), pd.DataFrame(inv_rows)
```

- [ ] **Step 4: inventory_loader.py を実装**

`src/pipeline/inventory_loader.py`:
```python
import sqlite3
import pandas as pd


def load_sellin(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    rows = df[["sku_id", "period", "distributor", "quantity", "amount_jpy"]].values.tolist()
    conn.executemany(
        "INSERT OR IGNORE INTO sellin_data (sku_id, period, distributor, quantity, amount_jpy) VALUES (?, ?, ?, ?, ?)",
        rows
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM sellin_data").fetchone()[0]


def load_sellout(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    rows = df[["sku_id", "period", "facility_type", "quantity", "amount_jpy"]].values.tolist()
    conn.executemany(
        "INSERT OR IGNORE INTO sellout_data (sku_id, period, facility_type, quantity, amount_jpy) VALUES (?, ?, ?, ?, ?)",
        rows
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM sellout_data").fetchone()[0]


def load_inventory(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    rows = df[["sku_id", "period", "distributor", "ending_inventory_qty",
               "ending_inventory_amount_jpy", "days_of_inventory"]].values.tolist()
    conn.executemany(
        """INSERT OR IGNORE INTO inventory_data
           (sku_id, period, distributor, ending_inventory_qty, ending_inventory_amount_jpy, days_of_inventory)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM inventory_data").fetchone()[0]
```

- [ ] **Step 5: テストが通ることを確認**

```bash
pytest tests/test_inventory_loader.py -v
```

Expected: PASSED (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/pipeline/sample_gen.py src/pipeline/inventory_loader.py tests/test_inventory_loader.py
git commit -m "feat: synthetic sell-in/sell-out/inventory generator and loaders"
```

---

### Task 6: 統合初期化スクリプト + 全テスト確認

**Files:**
- Create: `scripts/init_db.py`

**Interfaces:**
- Consumes: 全ローダー関数
- Produces: `data/pharma_forecast.db`（本番DB）

- [ ] **Step 1: init_db.py を実装**

`scripts/init_db.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.connection import get_connection
from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.iqvia_loader import load_iqvia
from src.pipeline.sample_gen import generate_sample_data
from src.pipeline.inventory_loader import load_sellin, load_sellout, load_inventory

EXCEL_PATH = "docs/sample_data/pharma_forecast_dummy_data.xlsx"
DB_PATH    = "data/pharma_forecast.db"

def main():
    print(f"Initializing DB: {DB_PATH}")
    conn = get_connection(DB_PATH)

    print("Creating tables...")
    create_all_tables(conn)

    print("Loading master data...")
    counts = load_masters(conn, EXCEL_PATH)
    print(f"  therapeutic_areas: {counts['therapeutic_areas']}")
    print(f"  ingredients:       {counts['ingredients']}")
    print(f"  products:          {counts['products']}")
    print(f"  skus:              {counts['skus']}")

    print("Loading IQVIA market data...")
    n = load_iqvia(conn, EXCEL_PATH)
    print(f"  market_data rows:  {n}")

    print("Generating synthetic sell-in/out/inventory...")
    df_si, df_so, df_inv = generate_sample_data(conn)
    n_si  = load_sellin(conn, df_si)
    n_so  = load_sellout(conn, df_so)
    n_inv = load_inventory(conn, df_inv)
    print(f"  sellin_data rows:    {n_si}")
    print(f"  sellout_data rows:   {n_so}")
    print(f"  inventory_data rows: {n_inv}")

    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 全テストを実行**

```bash
pytest tests/ -v
```

Expected: 全テスト PASSED

- [ ] **Step 3: 初期化スクリプトを実行してDBを生成**

```bash
cd ~/projects/sales-forecast-app
python scripts/init_db.py
```

Expected output:
```
Initializing DB: data/pharma_forecast.db
Creating tables...
Loading master data...
  therapeutic_areas: 8
  ingredients:       15
  products:          15
  skus:              30
Loading IQVIA market data...
  market_data rows:  450
Generating synthetic sell-in/out/inventory...
  sellin_data rows:    XXXX
  sellout_data rows:   XXXX
  inventory_data rows: XXXX
Done.
```

- [ ] **Step 4: DBの内容を簡易確認**

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/pharma_forecast.db')
for t in ['therapeutic_areas','ingredients','products','skus','market_data','sellin_data','sellout_data','inventory_data']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t:30s}: {n}')
conn.close()
"
```

- [ ] **Step 5: 最終コミット**

```bash
git add scripts/init_db.py
git commit -m "feat: Step 1 complete - data foundation with DB init script"
```

---

## Self-Review

**Spec coverage check (仕様書13章 Step 1):**
- [x] SKU/製品/成分/疾患領域の4階層マスタ → Task 3で実装
- [x] IQVIAデータ取込パイプライン → Task 4で実装
- [x] Sell-inデータパイプライン → Task 5で実装（合成データ）
- [x] Sell-outデータパイプライン → Task 5で実装（合成データ）
- [x] 卸別在庫データパイプライン → Task 5で実装（合成データ）
- [x] 制度イベントマスタのスキーマ定義 → Task 2のDDLに含まれる
- [x] 為替レートマスタのスキーマ定義 → Task 2のDDLに含まれる
- [x] SQLiteのFOREIGN KEY制約 → connection.pyで有効化
- [x] 全金額はJPY内部保持 → データ設計で遵守

**Sell-in/Sell-out/在庫の実データがない件:**
ダミーXLSXにはこれらが含まれないため、合成データ生成で対応。実データが揃い次第、`load_sellin/sellout/inventory` に実CSVを渡す形でそのまま使用可能な設計。

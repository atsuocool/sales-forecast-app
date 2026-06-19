import sqlite3
from typing import List, Optional

import numpy as np


DEFAULT_RATE_JPY_PER_USD = 150.0   # CSV がない場合のフォールバック


def get_forecast_rate(conn: sqlite3.Connection) -> float:
    """
    予測期間に適用する為替レート（JPY/USD）を返す。
    fx_rates テーブルの forecast_assumption レコードのうち最新のものを使用。
    存在しない場合は historical の直近レートを試み、それもなければデフォルト値を返す。
    """
    row = conn.execute(
        """
        SELECT jpy_per_usd FROM fx_rates
        WHERE rate_type = 'forecast_assumption'
        ORDER BY period DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        return float(row[0])

    row = conn.execute(
        """
        SELECT jpy_per_usd FROM fx_rates
        WHERE rate_type = 'historical'
        ORDER BY period DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        return float(row[0])

    return DEFAULT_RATE_JPY_PER_USD


def convert_amounts(
    amounts_jpy: np.ndarray,
    currency: str,
    rate_jpy_per_usd: float,
) -> np.ndarray:
    """
    JPY 配列を指定通貨に換算して返す。
    currency: "JPY" または "USD"
    rate_jpy_per_usd: 1 USD = N JPY
    """
    if currency == "JPY":
        return amounts_jpy.copy()
    if currency == "USD":
        return amounts_jpy / rate_jpy_per_usd
    raise ValueError(f"未対応の通貨コード: {currency!r}。'JPY' または 'USD' を指定してください。")


def format_amount(value: float, currency: str) -> str:
    """金額を通貨記号付きの文字列にフォーマットする。"""
    if currency == "JPY":
        return f"¥{value:,.0f}"
    if currency == "USD":
        return f"${value:,.0f}"
    return f"{value:,.2f} {currency}"

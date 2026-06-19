"""Shared FinMind historical price access helpers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

import pandas as pd
import streamlit as st

from data_layer.finmind_api import fetch_finmind_price_frame


DateLike = date | datetime | str


def _format_date(value: DateLike) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_cached_finmind_price_history(
    symbol: str,
    start_date: DateLike,
    end_date: DateLike,
    token: str = "",
    timeout: int = 30,
    sleep_seconds: float = 1.2,
    raise_on_rate_limit: bool = False,
):
    """Fetch FinMind TaiwanStockPrice data through one shared Streamlit cache."""
    return fetch_finmind_price_frame(
        str(symbol).strip(),
        _format_date(start_date),
        _format_date(end_date),
        token=token,
        timeout=timeout,
        sleep_seconds=sleep_seconds,
        raise_on_rate_limit=raise_on_rate_limit,
    )


def clean_price_history(
    df: pd.DataFrame,
    required_columns: Iterable[str] = ("date", "close"),
) -> pd.DataFrame:
    """Return price history sorted by date after dropping rows missing required fields."""
    if df.empty:
        return pd.DataFrame()

    required = list(required_columns)
    if any(column not in df.columns for column in required):
        return pd.DataFrame()

    return df.dropna(subset=required).sort_values("date").reset_index(drop=True)

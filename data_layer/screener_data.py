"""Shared data helpers for Streamlit screener pages."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from data_layer.historical_price_service import clean_price_history, fetch_cached_finmind_price_history
from data_layer.market_api import fetch_json_tpex as fetch_json_tpex_base
from data_layer.mops_revenue import fetch_mops_recent_revenue_frame
from data_layer.time_utils import taipei_now


URL_TPEX_PRICE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_tpex_price_rows(url: str = URL_TPEX_PRICE) -> list:
    return fetch_json_tpex_base(url)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_screener_mops_revenue(latest_ym: str, months: int, cache_version: str = "") -> pd.DataFrame:
    _ = cache_version
    return fetch_mops_recent_revenue_frame(latest_ym, months=months)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_screener_price_history(
    symbol: str,
    start_date: str,
    end_date: str,
    token: str = "",
    required_columns: tuple[str, ...] = ("date", "close"),
    timeout: int = 30,
    sleep_seconds: float = 1.2,
) -> pd.DataFrame:
    df, status_code, msg, retry_after = fetch_cached_finmind_price_history(
        symbol,
        start_date,
        end_date,
        token=token,
        timeout=timeout,
        sleep_seconds=sleep_seconds,
        raise_on_rate_limit=False,
    )
    if status_code in (402, 403, 429):
        raise RuntimeError(f"FINMIND_LIMIT:{status_code}:{retry_after}:{msg}")
    if status_code != 200 or df.empty:
        return pd.DataFrame()

    df = clean_price_history(df, required_columns=required_columns)
    if df.empty:
        return pd.DataFrame()

    columns = [column for column in ["date", "open", "high", "low", "close", "volume"] if column in df.columns]
    return df[columns]


def parse_finmind_retry_seconds(error_msg: str):
    parts = str(error_msg).split(":", 3)
    numeric_parts = []
    for part in parts[1:]:
        try:
            numeric_parts.append(max(int(float(part)), 0))
        except Exception:
            continue
    if not numeric_parts:
        return None
    return numeric_parts[1] if len(numeric_parts) >= 2 else numeric_parts[0]


def parse_finmind_limit_status(error_msg: str):
    parts = str(error_msg).split(":", 3)
    if len(parts) < 2:
        return None
    try:
        return int(float(parts[1]))
    except Exception:
        return None


def parse_finmind_limit(error_msg: str) -> tuple[int | None, object | None]:
    parts = str(error_msg).split(":", 3)
    status = parse_finmind_limit_status(error_msg)
    retry_after = parts[2] if len(parts) >= 3 else None
    return status, retry_after


def format_wait_time(seconds):
    if seconds is None:
        return "未知"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours} 小時 {minutes} 分 {sec} 秒"
    if minutes > 0:
        return f"{minutes} 分 {sec} 秒"
    return f"{sec} 秒"


def format_retry_at(seconds):
    if seconds is None:
        return "未知"
    retry_at = taipei_now() + timedelta(seconds=int(seconds))
    return retry_at.strftime("%H:%M:%S")

import pandas as pd
import requests
import streamlit as st
import time

from data_layer.market_api import DEFAULT_HEADERS
from data_layer.market_data import build_institutional_net_buy_frame


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_twse_3insti(date_ymd: str) -> pd.DataFrame:
    """Fetch TWSE institutional net buy/sell data for a single YYYYMMDD date."""
    urls = [
        (
            "TWSE RWD T86",
            "https://www.twse.com.tw/rwd/zh/fund/T86"
            f"?date={date_ymd}&selectType=ALLBUT0999&response=json",
        ),
        (
            "TWSE legacy T86",
            "https://www.twse.com.tw/fund/T86"
            f"?response=json&date={date_ymd}&selectType=ALLBUT0999",
        ),
    ]
    headers = {
        **DEFAULT_HEADERS,
        "Accept": "application/json,text/plain,*/*",
        "Connection": "close",
    }
    last_error = None
    for source, url in urls:
        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=(5, 8), headers=headers)
                resp.raise_for_status()
                result = resp.json()
                stat = str(result.get("stat", ""))
                if stat != "OK" or not result.get("data"):
                    if "沒有符合條件" in stat:
                        return pd.DataFrame()
                    raise RuntimeError(f"{source} 非預期回應：{stat or result}")

                df = pd.DataFrame(result["data"], columns=result["fields"])
                col_f = next(
                    (c for c in df.columns if "不含外資自營商" in c and "買賣超" in c),
                    None,
                )
                col_fd = next((c for c in df.columns if "外資自營商買賣超" in c), None)
                if col_f is None:
                    raise ValueError(f"{source} 欄位異常，實際欄位：{list(df.columns)}")

                return build_institutional_net_buy_frame(
                    stock_ids=df["證券代號"],
                    primary_net_shares=df[col_f].astype(str).str.replace(",", ""),
                    secondary_net_shares=(
                        df[col_fd].astype(str).str.replace(",", "") if col_fd else None
                    ),
                )
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.8 * (attempt + 1))

    raise RuntimeError(f"TWSE 三大法人 API 讀取失敗：{last_error}") from last_error


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_tpex_3insti(date_roc: str) -> pd.DataFrame:
    """Fetch TPEX institutional net buy/sell data for a single ROC date."""
    url_open = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_3insti_quotes"
    openapi_error = None
    try:
        resp = requests.get(url_open, timeout=20, headers=DEFAULT_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError("empty")

        df = pd.DataFrame(data)
        col_id = next(
            (c for c in df.columns if "Code" in c or "SecuritiesCompanyCode" in c),
            None,
        )
        col_f = next(
            (
                c
                for c in df.columns
                if "ForeignInvestment" in c and "Net" in c and "Shares" in c
            ),
            None,
        )
        col_fd = next(
            (
                c
                for c in df.columns
                if "DealerHedging" in c and "Net" in c and "Shares" in c
            ),
            None,
        )
        if col_id is None or col_f is None:
            raise ValueError(f"欄位異常：{list(df.columns)}")

        return build_institutional_net_buy_frame(
            stock_ids=df[col_id],
            primary_net_shares=df[col_f].astype(str).str.replace(",", ""),
            secondary_net_shares=(
                df[col_fd].astype(str).str.replace(",", "") if col_fd else None
            ),
        )
    except Exception as exc:
        openapi_error = exc

    url_old = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        f"3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={date_roc}&s=0,asc&o=json"
    )
    try:
        resp = requests.get(url_old, timeout=20, headers=DEFAULT_HEADERS)
        resp.raise_for_status()
        result = resp.json()
        tables = result.get("tables", [])
        if not tables or not tables[0].get("data"):
            return pd.DataFrame()

        header = tables[0].get("fields", []) or tables[0].get("title", [])
        df = pd.DataFrame(tables[0]["data"])
        col_f = next(
            (
                i
                for i, h in enumerate(header)
                if "不含外資自營商" in str(h) and "買賣超" in str(h)
            ),
            None,
        )
        col_fd = next(
            (
                i
                for i, h in enumerate(header)
                if "外資自營商" in str(h) and "買賣超" in str(h)
            ),
            None,
        )
        if col_f is None:
            col_f = 4
        if col_fd is None and df.shape[1] > 7:
            col_fd = 7

        return build_institutional_net_buy_frame(
            stock_ids=df[0],
            primary_net_shares=df[col_f].astype(str).str.replace(",", ""),
            secondary_net_shares=(
                df[col_fd].astype(str).str.replace(",", "")
                if col_fd is not None
                else None
            ),
        )
    except Exception as exc:
        detail = f"OpenAPI: {openapi_error}; 舊版 API: {exc}" if openapi_error else str(exc)
        raise RuntimeError(f"TPEX 三大法人 API 讀取失敗：{detail}") from exc

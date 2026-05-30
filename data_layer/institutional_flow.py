import pandas as pd
import requests
import streamlit as st

from data_layer.market_api import DEFAULT_HEADERS
from data_layer.market_data import build_institutional_net_buy_frame


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_twse_3insti(date_ymd: str) -> pd.DataFrame:
    """Fetch TWSE institutional net buy/sell data for a single YYYYMMDD date."""
    url = (
        "https://www.twse.com.tw/fund/T86"
        f"?response=json&date={date_ymd}&selectType=ALLBUT0999"
    )
    try:
        resp = requests.get(url, timeout=20, headers=DEFAULT_HEADERS)
        result = resp.json()
        if result.get("stat") != "OK" or not result.get("data"):
            return pd.DataFrame()

        df = pd.DataFrame(result["data"], columns=result["fields"])
        col_f = next(
            (c for c in df.columns if "不含外資自營商" in c and "買賣超" in c),
            None,
        )
        col_fd = next((c for c in df.columns if "外資自營商買賣超" in c), None)
        if col_f is None:
            st.warning(
                f"TWSE T86 找不到外資欄位，實際欄位：{list(df.columns)}"
            )
            return pd.DataFrame()

        return build_institutional_net_buy_frame(
            stock_ids=df["證券代號"],
            primary_net_shares=df[col_f].astype(str).str.replace(",", ""),
            secondary_net_shares=(
                df[col_fd].astype(str).str.replace(",", "") if col_fd else None
            ),
        )
    except Exception as exc:
        st.warning(f"TWSE 三大法人 API 讀取失敗：{exc}")
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_tpex_3insti(date_roc: str) -> pd.DataFrame:
    """Fetch TPEX institutional net buy/sell data for a single ROC date."""
    url_open = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_3insti_quotes"
    try:
        resp = requests.get(url_open, timeout=20, headers=DEFAULT_HEADERS)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError("empty")

        df = pd.DataFrame(data)
        col_id = next(
            (
                c
                for c in df.columns
                if "Code" in c or "SecuritiesCompanyCode" in c
            ),
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
            raise ValueError(f"欄位不足：{list(df.columns)}")

        return build_institutional_net_buy_frame(
            stock_ids=df[col_id],
            primary_net_shares=df[col_f].astype(str).str.replace(",", ""),
            secondary_net_shares=(
                df[col_fd].astype(str).str.replace(",", "") if col_fd else None
            ),
        )
    except Exception:
        pass

    url_old = (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        f"3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={date_roc}&s=0,asc&o=json"
    )
    try:
        resp = requests.get(url_old, timeout=20, headers=DEFAULT_HEADERS)
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
                if "外資自營商" in str(h) and "不含" not in str(h)
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
        st.warning(f"TPEX 三大法人 API 讀取失敗：{exc}")
        return pd.DataFrame()

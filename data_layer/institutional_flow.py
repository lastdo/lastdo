import pandas as pd
import requests
import streamlit as st
import time

from data_layer.market_api import DEFAULT_HEADERS, fetch_json_tpex
from data_layer.market_data import build_institutional_net_buy_frame


def _find_tpex_foreign_net_columns(columns) -> tuple[str | None, str | None]:
    column_names = [str(column) for column in columns]
    total_keys = [
        "ForeignInvestorsInclude MainlandAreaInvestors-Difference",
        "ForeignInvestorsIncludeMainlandAreaInvestors-Difference",
        " ForeignInvestorsIncludeMainlandAreaInvestors-Difference",
        " ForeignInvestorsInclude MainlandAreaInvestors-Difference",
    ]
    for key in total_keys:
        if key in column_names:
            return key, None

    primary = next(
        (
            column
            for column in column_names
            if "Foreign Investors include Mainland Area Investors" in column
            and "excluded" in column
            and "Difference" in column
        ),
        None,
    )
    secondary = next(
        (
            column
            for column in column_names
            if column.strip() in {"ForeignDealers-Difference", "Foreign Dealers-Difference"}
        ),
        None,
    )
    return primary, secondary


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
    _ = date_roc
    url_open = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
    try:
        data = fetch_json_tpex(url_open)
        if not data:
            raise ValueError("empty")

        df = pd.DataFrame(data)
        col_id = next(
            (c for c in df.columns if "Code" in c or "SecuritiesCompanyCode" in c),
            None,
        )
        col_f, col_fd = _find_tpex_foreign_net_columns(df.columns)
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
        raise RuntimeError(f"TPEX 三大法人 API 讀取失敗：OpenAPI: {exc}") from exc

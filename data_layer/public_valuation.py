import pandas as pd
import streamlit as st

from data_layer.data_diagnostics import fetch_json_with_diagnostic
from data_layer.market_data import build_public_pe_snapshot
from data_layer.market_api import fetch_json_tpex, fetch_json_twse


URL_TWSE_PE = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
URL_TPEX_PE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
PUBLIC_PE_LABEL = "官方上市櫃API（近四季EPS反推）"


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_public_pe_ratios() -> pd.DataFrame:
    """Fetch official TWSE/TPEX PE ratios and normalize to a single schema."""
    try:
        raw_twse = fetch_json_twse(URL_TWSE_PE)
    except Exception:
        raw_twse = []

    try:
        raw_tpex = fetch_json_tpex(URL_TPEX_PE)
    except Exception:
        raw_tpex = []

    return build_public_pe_snapshot(raw_twse, raw_tpex)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_public_pe_ratios_with_diagnostics() -> tuple[pd.DataFrame, list[dict]]:
    """Fetch official PE ratios with per-source diagnostics."""
    raw_twse, diag_twse = fetch_json_with_diagnostic(
        fetch_json_twse,
        URL_TWSE_PE,
        "TWSE 官方本益比",
    )
    raw_tpex, diag_tpex = fetch_json_with_diagnostic(
        fetch_json_tpex,
        URL_TPEX_PE,
        "TPEX 官方本益比",
    )

    df = build_public_pe_snapshot(raw_twse, raw_tpex)
    diagnostics = [diag_twse.to_dict(), diag_tpex.to_dict()]
    if df.empty:
        for item in diagnostics:
            if item["status"] == "complete":
                item["status"] = "partial"
                item["message"] = "來源有回應，但可用本益比資料為空，欄位可能異動。"
    return df, diagnostics


def attach_public_valuation(
    df: pd.DataFrame,
    df_public_pe: pd.DataFrame,
    price_col: str = "close",
) -> pd.DataFrame:
    """Attach official PE and reverse-computed trailing-4Q EPS to a stock dataframe."""
    merged = df.merge(df_public_pe, on="stock_id", how="left")
    merged["pe_ratio"] = pd.to_numeric(merged["pe_ratio_public"], errors="coerce")
    merged["ttm_eps"] = pd.NA

    valid_mask = merged["pe_ratio"].notna() & (merged["pe_ratio"] > 0)
    merged.loc[valid_mask, "ttm_eps"] = (
        pd.to_numeric(merged.loc[valid_mask, price_col], errors="coerce")
        / merged.loc[valid_mask, "pe_ratio"]
    )
    merged["ttm_eps"] = pd.to_numeric(merged["ttm_eps"], errors="coerce")
    merged.loc[merged["ttm_eps"] <= 0, "ttm_eps"] = pd.NA

    merged["pe_label"] = pd.NA
    merged.loc[valid_mask, "pe_label"] = PUBLIC_PE_LABEL
    return merged

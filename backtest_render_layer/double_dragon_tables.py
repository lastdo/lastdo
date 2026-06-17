from __future__ import annotations

import pandas as pd
import streamlit as st

from data_layer.export_utils import dataframe_to_csv_bytes


DISPLAY_COLUMNS = {
    "as_of_date": "基準日",
    "stock_id": "股票代號",
    "stock_name": "股票名稱",
    "market": "市場",
    "price_date": "價格日期",
    "close": "收盤價",
    "vol_lot": "成交量(張)",
    "avg_rev_yoy": "近兩月平均營收年增(%)",
    "rev_months": "營收月份",
    "ttm_eps": "近四季EPS",
    "eps_quarters": "EPS季度",
    "pe_ratio": "PE",
    "ma60": "季線",
    "ma60_premium_pct": "季線溢價(%)",
    "six_month_low": "六個月最低價",
    "six_month_low_date": "最低價日期",
    "low_premium_pct": "低點溢價(%)",
    "is_common_pass": "共用條件",
    "is_dragon_rise_pass": "龍騰升空",
    "is_dragon_hidden_pass": "潛龍在淵",
    "fail_reason": "落選原因",
}


def make_display_df(df: pd.DataFrame, include_audit: bool = False) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=list(DISPLAY_COLUMNS.values()))

    columns = list(DISPLAY_COLUMNS)
    if not include_audit:
        columns = [
            "as_of_date",
            "stock_id",
            "stock_name",
            "market",
            "price_date",
            "close",
            "vol_lot",
            "avg_rev_yoy",
            "rev_months",
            "ttm_eps",
            "eps_quarters",
            "pe_ratio",
            "ma60",
            "ma60_premium_pct",
            "six_month_low",
            "six_month_low_date",
            "low_premium_pct",
        ]
    display = df[[column for column in columns if column in df.columns]].rename(columns=DISPLAY_COLUMNS).copy()
    for column in [
        "收盤價",
        "成交量(張)",
        "近兩月平均營收年增(%)",
        "近四季EPS",
        "PE",
        "季線",
        "季線溢價(%)",
        "六個月最低價",
        "低點溢價(%)",
    ]:
        if column in display.columns:
            display[column] = pd.to_numeric(display[column], errors="coerce").round(2)
    if "收盤價" in display.columns:
        display = display.sort_values("收盤價", ascending=False)
    return display.reset_index(drop=True)


def render_snapshot_table(df: pd.DataFrame, include_audit: bool = False) -> pd.DataFrame:
    display_df = make_display_df(df, include_audit=include_audit)
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
            "成交量(張)": st.column_config.NumberColumn("成交量(張)", format="%.0f"),
            "近兩月平均營收年增(%)": st.column_config.NumberColumn("近兩月平均營收年增(%)", format="%.2f"),
            "近四季EPS": st.column_config.NumberColumn("近四季EPS", format="%.2f"),
            "PE": st.column_config.NumberColumn("PE", format="%.2f"),
            "季線": st.column_config.NumberColumn("季線", format="%.2f"),
            "季線溢價(%)": st.column_config.NumberColumn("季線溢價(%)", format="%.2f"),
            "六個月最低價": st.column_config.NumberColumn("六個月最低價", format="%.2f"),
            "低點溢價(%)": st.column_config.NumberColumn("低點溢價(%)", format="%.2f"),
        },
    )
    return display_df


def render_download(display_df: pd.DataFrame, label: str, file_name: str) -> None:
    st.download_button(
        label=label,
        data=dataframe_to_csv_bytes(display_df),
        file_name=file_name,
        mime="text/csv",
        disabled=display_df.empty,
        use_container_width=True,
    )

"""Shared render helpers for strategy screener pages."""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st


FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RESULT_VIEW_OPTIONS = ["標記說明", "明細表", "診斷與資料"]
INVESTMENT_DISCLAIMER = "📢 本系統僅供學術研究，不構成投資建議"


def render_page_positioning(items: list[dict[str, str]]) -> None:
    columns = st.columns(len(items))
    for column, item in zip(columns, items):
        with column:
            st.markdown(
                f"""
**{item["title"]}**

{item["body"]}
"""
            )


def render_strategy_card(metrics: list[tuple[str, str]], caption: str, note: str = "") -> None:
    columns = st.columns(len(metrics))
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)
    st.caption(caption)
    if note:
        st.caption(note)


def render_result_view_selector(key: str, default: str = "標記說明") -> str:
    current = st.session_state.get(key, default)
    if current not in RESULT_VIEW_OPTIONS:
        current = default
    return st.radio(
        "結果檢視",
        RESULT_VIEW_OPTIONS,
        index=RESULT_VIEW_OPTIONS.index(current),
        key=key,
        horizontal=True,
        label_visibility="collapsed",
    )


def validate_family_id(family_id: str, message: str) -> None:
    if FAMILY_ID_PATTERN.fullmatch(family_id):
        return
    st.error(message)
    st.stop()


def render_alert_summary(display_df: pd.DataFrame, labels: list[str], alert_col: str = "警示標記") -> None:
    if display_df.empty or alert_col not in display_df.columns:
        return

    flattened = "｜".join(display_df[alert_col].astype(str).tolist())
    columns = st.columns(len(labels))
    for column, label in zip(columns, labels):
        column.metric(label, flattened.count(label))

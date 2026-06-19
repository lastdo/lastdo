"""Shared sidebar navigation helpers."""
from __future__ import annotations

import streamlit as st


NAV_ITEMS = [
    ("inventory", "庫存管理", "Inventory.py"),
    ("app_tw", "AI 台股分析", "pages/1_app_tw.py"),
    ("analysis_history", "分析紀錄", "pages/2_analysis_history.py"),
    ("growth_screener", "雙龍吐珠", "pages/3_growth_screener.py"),
    ("chip_screener", "法人重壓股", "pages/4_chip_screener.py"),
    ("bottom_screener", "底部剛起漲", "pages/5_bottom_screener.py"),
    ("strategy_backtest", "雙龍吐珠策略回測", "pages/6_strategy_backtest.py"),
]

NAV_LABELS = {page_key: label for page_key, label, _target in NAV_ITEMS}


def render_global_navigation(current_page: str) -> None:
    """Render the shared sidebar navigation used across all pages."""
    st.header("功能導覽")
    st.caption("選擇要使用的分析工具。")

    for page_key, label, target in NAV_ITEMS:
        is_current = current_page == page_key
        if st.button(
            label,
            use_container_width=True,
            type="primary" if is_current else "secondary",
            key=f"nav_{page_key}",
            disabled=is_current,
        ):
            st.switch_page(target)

    st.markdown("---")
    st.caption(f"目前頁面：{NAV_LABELS.get(current_page, current_page)}")

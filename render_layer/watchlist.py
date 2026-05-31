from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_layer.portfolio_store import create_portfolio_item, load_portfolio


def format_watchlist_number(value, suffix: str = "") -> str:
    return f"{value:.2f}{suffix}" if pd.notna(value) else f"—{suffix}"


def render_watchlist_adder(
    result_df: pd.DataFrame,
    family_id: str,
    *,
    select_columns: list[str],
    numeric_columns: list[str],
    label_builder: Callable[[pd.Series], str],
    chart_loader: Callable[[str, str], pd.DataFrame],
    selectbox_key: str,
    add_button_key: str,
    finmind_token: str = "",
    caption_builder: Callable[[dict, pd.DataFrame], str] | None = None,
    support_line_builder: Callable[[dict], float | None] | None = None,
) -> None:
    if result_df.empty:
        return

    portfolio_items = load_portfolio(family_id)
    existing_symbols = {
        str(item.get("stock_id") or item.get("symbol") or "").strip()
        for item in portfolio_items
    }

    action_df = result_df[select_columns].copy()
    for column in numeric_columns:
        action_df[column] = pd.to_numeric(action_df[column], errors="coerce")
    action_df["label"] = action_df.apply(label_builder, axis=1)

    options = action_df.to_dict("records")
    default_index = next(
        (idx for idx, row in enumerate(options) if row["stock_id"] not in existing_symbols),
        0,
    )

    st.markdown("#### 加入庫存股自選名單")
    st.caption(f"目標 family_id：`{family_id}`。加入後會以「自選股」形式出現在庫存股頁，不會填入持有成本與股數。")
    selected = st.selectbox(
        "選擇要加入自選股的股票",
        options=options,
        index=default_index,
        format_func=lambda row: row["label"],
        key=selectbox_key,
    )

    selected_symbol = str(selected["stock_id"]).strip()
    already_exists = selected_symbol in existing_symbols
    chart_df = chart_loader(selected_symbol, finmind_token)

    st.markdown("#### 技術線型")
    chart_df = _render_price_ma_chart(
        chart_df,
        support_line=support_line_builder(selected) if support_line_builder else None,
    )

    if caption_builder:
        st.caption(caption_builder(selected, chart_df))
    if already_exists:
        st.info(f"{selected_symbol} 已經在這組 family_id 的持股 / 自選股清單中。")

    if st.button(
        "加入自選股",
        type="primary",
        disabled=already_exists,
        use_container_width=True,
        key=add_button_key,
    ):
        create_portfolio_item(
            family_id=family_id,
            stock_id=selected_symbol,
            stock_name=str(selected["stock_name"]).strip(),
        )
        st.success(f"已將 {selected_symbol} {selected['stock_name']} 加入自選股。")
        st.rerun()


def _render_price_ma_chart(chart_df: pd.DataFrame, support_line: float | None = None) -> pd.DataFrame:
    if chart_df.empty:
        st.info("這檔股票暫時抓不到技術線型資料，請稍後再試。")
        return chart_df

    chart_df = chart_df.copy().sort_values("date").reset_index(drop=True)
    if "ma20" not in chart_df.columns:
        chart_df["ma20"] = chart_df["close"].rolling(20, min_periods=1).mean()
    if "ma60" not in chart_df.columns:
        chart_df["ma60"] = chart_df["close"].rolling(60, min_periods=1).mean()
    chart_df = chart_df.tail(120).reset_index(drop=True)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["close"],
            mode="lines",
            name="收盤價",
            line=dict(color="#1d4ed8", width=2.5),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["ma20"],
            mode="lines",
            name="MA20",
            line=dict(color="#f59e0b", width=1.8),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=chart_df["date"],
            y=chart_df["ma60"],
            mode="lines",
            name="MA60",
            line=dict(color="#16a34a", width=2),
        )
    )
    if support_line is not None and pd.notna(support_line):
        fig.add_hline(y=float(support_line), line_dash="dot", line_color="#dc2626", annotation_text="支撐價")

    fig.update_layout(
        height=300,
        margin=dict(l=8, r=8, t=10, b=8),
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(showgrid=True, gridcolor="#e5edf7", title=None)
    st.plotly_chart(fig, use_container_width=True)
    return chart_df


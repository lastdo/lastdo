from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backtest_data_layer.performance import PerformanceDiagnostics
from data_layer.export_utils import dataframe_to_csv_bytes


RETURN_COLUMNS = {
    "stock_id": "股票代碼",
    "stock_name": "股票名稱",
    "branch_label": "策略分支",
    "start_date": "進場日",
    "end_date": "出場日",
    "start_price": "進場價",
    "end_price": "出場價",
    "stock_return_pct": "個股報酬(%)",
    "benchmark_return_pct": "大盤報酬(%)",
    "excess_return_pct": "超額報酬(%)",
}


def _format_pct(value) -> str:
    number = pd.to_numeric(value, errors="coerce")
    return "NA" if pd.isna(number) else f"{float(number):+.2f}%"


def _format_plain_pct(value) -> str:
    number = pd.to_numeric(value, errors="coerce")
    return "NA" if pd.isna(number) else f"{float(number):.1f}%"


def render_performance_kpis(kpis: dict, diagnostics: PerformanceDiagnostics) -> None:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("投組報酬", _format_pct(kpis.get("portfolio_return_pct")))
    col2.metric("大盤報酬", _format_pct(kpis.get("benchmark_return_pct")), diagnostics.benchmark_id)
    col3.metric("超額報酬", _format_pct(kpis.get("excess_return_pct")))
    col4.metric("勝率", _format_plain_pct(kpis.get("win_rate_pct")))
    col5.metric("可計算檔數", f"{diagnostics.priced_stocks} / {diagnostics.requested_stocks}")

    col6, col7, col8 = st.columns(3)
    col6.metric("中位數報酬", _format_pct(kpis.get("median_return_pct")))
    col7.metric("最佳個股", kpis.get("best_stock") or "NA")
    col8.metric("最弱個股", kpis.get("worst_stock") or "NA")

    if diagnostics.rate_limit_error:
        st.warning(f"FinMind 查詢受限，績效資料不完整：{diagnostics.rate_limit_error}")
    if diagnostics.failed_stocks:
        st.caption("未能取得出場價：" + ", ".join(diagnostics.failed_stocks[:12]))


def render_performance_chart(curve_df: pd.DataFrame) -> None:
    if curve_df.empty:
        st.info("尚無可繪製的報酬曲線。")
        return

    fig = go.Figure()
    lines = [
        ("portfolio_return_pct", "投組報酬"),
        ("benchmark_return_pct", "大盤報酬"),
        ("excess_return_pct", "超額報酬"),
    ]
    for column, label in lines:
        if column in curve_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=curve_df["date"],
                    y=pd.to_numeric(curve_df[column], errors="coerce"),
                    mode="lines",
                    name=label,
                )
            )
    fig.update_layout(
        template="plotly_dark",
        height=420,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="報酬率(%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def make_return_display_df(return_df: pd.DataFrame) -> pd.DataFrame:
    if return_df.empty:
        return pd.DataFrame(columns=list(RETURN_COLUMNS.values()))
    display = return_df[[column for column in RETURN_COLUMNS if column in return_df.columns]].rename(
        columns=RETURN_COLUMNS
    )
    for column in ["進場價", "出場價", "個股報酬(%)", "大盤報酬(%)", "超額報酬(%)"]:
        if column in display.columns:
            display[column] = pd.to_numeric(display[column], errors="coerce").round(2)
    if "超額報酬(%)" in display.columns:
        display = display.sort_values("超額報酬(%)", ascending=False)
    return display.reset_index(drop=True)


def render_return_table(return_df: pd.DataFrame, date_token: str) -> pd.DataFrame:
    display_df = make_return_display_df(return_df)
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "進場價": st.column_config.NumberColumn("進場價", format="%.2f"),
            "出場價": st.column_config.NumberColumn("出場價", format="%.2f"),
            "個股報酬(%)": st.column_config.NumberColumn("個股報酬(%)", format="%.2f"),
            "大盤報酬(%)": st.column_config.NumberColumn("大盤報酬(%)", format="%.2f"),
            "超額報酬(%)": st.column_config.NumberColumn("超額報酬(%)", format="%.2f"),
        },
    )
    st.download_button(
        label="下載績效 CSV",
        data=dataframe_to_csv_bytes(display_df),
        file_name=f"double_dragon_performance_{date_token}.csv",
        mime="text/csv",
        disabled=display_df.empty,
        use_container_width=True,
    )
    return display_df

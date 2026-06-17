from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from backtest_data_layer.double_dragon_snapshot import (
    SnapshotDiagnostics,
    build_double_dragon_snapshot,
)
from backtest_render_layer.double_dragon_tables import render_download, render_snapshot_table
from data_layer.app_common import get_runtime_secret
from data_layer.time_utils import taipei_now, taipei_today
from render_layer.style import apply_style, page_header, render_global_navigation, render_meta_strip


load_dotenv()


st.set_page_config(page_title="雙龍吐珠策略回測", page_icon="🐉", layout="wide")
apply_style()
page_header(
    "🐉",
    "雙龍吐珠策略回測",
    "指定任意基準日，重建當天可取得資料下的龍騰升空與潛龍在淵選股池。",
)


def _default_as_of_date():
    return taipei_today() - timedelta(days=92)


def _result_key(as_of_date, max_targets: int) -> str:
    return f"double_dragon_backtest_snapshot:{as_of_date}:{max_targets}"


def render_summary(df_snapshot: pd.DataFrame, diagnostics: SnapshotDiagnostics) -> None:
    common_count = int(df_snapshot["is_common_pass"].sum()) if "is_common_pass" in df_snapshot.columns else 0
    dragon_count = int(df_snapshot["is_dragon_rise_pass"].sum()) if "is_dragon_rise_pass" in df_snapshot.columns else 0
    hidden_count = int(df_snapshot["is_dragon_hidden_pass"].sum()) if "is_dragon_hidden_pass" in df_snapshot.columns else 0
    unique_count = (
        df_snapshot[df_snapshot["is_dragon_rise_pass"] | df_snapshot["is_dragon_hidden_pass"]]["stock_id"].nunique()
        if not df_snapshot.empty
        else 0
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("共用池", f"{common_count} 檔")
    col2.metric("龍騰升空", f"{dragon_count} 檔")
    col3.metric("潛龍在淵", f"{hidden_count} 檔")
    col4.metric("雙龍不重複", f"{unique_count} 檔")
    col5.metric("已處理", f"{diagnostics.processed} / {diagnostics.revenue_candidates}")


def render_diagnostics(diagnostics: SnapshotDiagnostics) -> None:
    with st.expander("資料重建診斷", expanded=bool(diagnostics.rate_limit_error)):
        rows = [
            {"項目": "歷史價量股票數", "數值": diagnostics.price_rows, "說明": "TWSE/TPEX 基準日或最近交易日歷史價量"},
            {"項目": "價量候選", "數值": diagnostics.price_volume_candidates, "說明": "股價 > 60 且成交量 > 1000 張"},
            {"項目": "MOPS 起始月份", "數值": diagnostics.revenue_month_start, "說明": "由基準日前一個完整月份往前掃描"},
            {"項目": "MOPS 原始筆數", "數值": diagnostics.revenue_rows, "說明": "近月營收原始列數"},
            {"項目": "FinMind候選", "數值": diagnostics.revenue_candidates, "說明": "價量池 ∩ 近兩個非二月月份 YoY 平均 >= 20%"},
            {"項目": "價格失敗", "數值": len(diagnostics.price_failed), "說明": ", ".join(diagnostics.price_failed[:12])},
            {"項目": "EPS失敗", "數值": len(diagnostics.eps_failed), "說明": ", ".join(diagnostics.eps_failed[:12])},
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if diagnostics.rate_limit_error:
            st.error(f"FinMind 查詢受限，本次結果不完整：{diagnostics.rate_limit_error}")


render_meta_strip(
    [
        {"label": "基準日重建", "value": "任意 as_of_date", "sub": "不硬寫單一日期"},
        {"label": "資料時點", "value": "只看基準日前", "sub": "價量先篩，再接營收與 EPS"},
        {"label": "估值", "value": "FinMind EPS + 當日收盤", "sub": "PE = close / TTM EPS"},
        {"label": "輸出", "value": "雙龍池 + 稽核表", "sub": "表格依收盤價降冪"},
    ]
)

with st.sidebar:
    render_global_navigation("strategy_backtest")
    st.markdown("---")
    st.header("回測設定")
    as_of_date = st.date_input("選股基準日", value=_default_as_of_date())
    finmind_token = st.text_input(
        "FinMind Token（選填）",
        value=get_runtime_secret("FINMIND_TOKEN", ""),
        type="password",
        help="歷史股價與 EPS 使用 FinMind 查詢。",
    ).strip()
    max_targets = int(
        st.number_input(
            "最多處理營收候選檔數",
            value=0,
            min_value=0,
            step=50,
            help="0 表示全部處理；除錯時可先限制數量。",
        )
    )
    run_btn = st.button("重建基準日選股池", use_container_width=True, type="primary")
    if st.button("清除本頁結果", use_container_width=True):
        for key in list(st.session_state):
            if str(key).startswith("double_dragon_backtest_snapshot:"):
                st.session_state.pop(key, None)
        st.success("已清除本頁快取結果。")
        st.stop()


key = _result_key(as_of_date, max_targets)

if run_btn:
    status = st.empty()
    progress = st.progress(0, text="準備重建基準日資料池...")

    def update_progress(done: int, total: int, stock_id: str) -> None:
        ratio = min(done / total, 1.0) if total else 1.0
        progress.progress(ratio, text=f"FinMind 三線程重建：{done} / {total}（{stock_id}）")

    status.info("先用基準日歷史股價與成交量建立價量池，再接 MOPS 營收，最後才對候選股票查 FinMind EPS 與技術指標。")
    try:
        df_snapshot, diagnostics = build_double_dragon_snapshot(
            as_of_date,
            token=finmind_token,
            max_workers=3,
            max_targets=max_targets,
            progress_callback=update_progress,
        )
    except Exception as exc:
        progress.empty()
        st.error(f"重建失敗：{type(exc).__name__}: {exc}")
        st.stop()

    progress.progress(1.0, text="基準日資料池重建完成")
    st.session_state[key] = {"snapshot": df_snapshot, "diagnostics": diagnostics}
    status.empty()

saved = st.session_state.get(key)
if not saved:
    st.info("選擇基準日後，按下側邊欄的「重建基準日選股池」。第一版會先重建該日的雙龍選股池，不先計算持有期報酬。")
    st.stop()

df_snapshot = saved["snapshot"]
diagnostics = saved["diagnostics"]

st.subheader(f"{as_of_date} 雙龍吐珠選股池")
render_summary(df_snapshot, diagnostics)
render_diagnostics(diagnostics)

if diagnostics.rate_limit_error:
    st.warning("FinMind 查詢受限，本次資料池不完整，請稍後重跑或提供 Token。")

if df_snapshot.empty:
    st.warning("本次沒有可呈現的完整資料列。請先查看資料重建診斷，確認是條件沒有通過，還是資料來源抓取不足。")
    st.stop()

common_df = df_snapshot[df_snapshot["is_common_pass"]].copy()
dragon_df = df_snapshot[df_snapshot["is_dragon_rise_pass"]].copy()
hidden_df = df_snapshot[df_snapshot["is_dragon_hidden_pass"]].copy()
combined_df = pd.concat(
    [
        dragon_df.assign(strategy="龍騰升空"),
        hidden_df.assign(strategy="潛龍在淵"),
    ],
    ignore_index=True,
).sort_values("close", ascending=False)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["龍騰升空", "潛龍在淵", "雙龍合併", "共用池", "稽核明細"])
date_token = pd.to_datetime(as_of_date).strftime("%Y%m%d")

with tab1:
    display_df = render_snapshot_table(dragon_df)
    render_download(display_df, "下載龍騰升空 CSV", f"龍騰升空_{date_token}.csv")

with tab2:
    display_df = render_snapshot_table(hidden_df)
    render_download(display_df, "下載潛龍在淵 CSV", f"潛龍在淵_{date_token}.csv")

with tab3:
    display_df = render_snapshot_table(combined_df)
    render_download(display_df, "下載雙龍合併 CSV", f"雙龍吐珠合併_{date_token}.csv")

with tab4:
    display_df = render_snapshot_table(common_df)
    render_download(display_df, "下載共用池 CSV", f"雙龍共用池_{date_token}.csv")

with tab5:
    display_df = render_snapshot_table(df_snapshot, include_audit=True)
    render_download(display_df, "下載稽核明細 CSV", f"雙龍稽核明細_{date_token}.csv")

st.caption(
    f"資料重建時間：{taipei_now().strftime('%Y-%m-%d %H:%M:%S')}。"
    "基準日價量來自 TWSE/TPEX 歷史行情；月營收來自 MOPS；MA60、六個月低點與 EPS 來自 FinMind；PE 以基準日收盤價 / 近四季 EPS 計算。"
)

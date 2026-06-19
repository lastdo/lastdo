from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from backtest_data_layer.double_dragon_snapshot import (
    SnapshotDiagnostics,
    build_double_dragon_snapshot,
)
from backtest_data_layer.performance import build_return_analysis
from backtest_data_layer.supabase_store import (
    SupabaseBacktestStoreError,
    get_supabase_status,
    list_backtest_runs,
    load_backtest_snapshot,
    save_backtest_snapshot,
)
from backtest_render_layer.double_dragon_tables import render_download, render_snapshot_table
from backtest_render_layer.performance import (
    render_performance_chart,
    render_performance_kpis,
    render_return_table,
)
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


def _performance_key(as_of_date, end_date, max_targets: int, max_stocks: int) -> str:
    return f"double_dragon_backtest_performance:{as_of_date}:{end_date}:{max_targets}:{max_stocks}"


SUPABASE_LOADED_KEY = "double_dragon_backtest_supabase_loaded"
SUPABASE_RUNS_KEY = "double_dragon_backtest_supabase_runs"


def _format_supabase_run(run: dict) -> str:
    created_at = str(run.get("created_at") or "")[:19].replace("T", " ")
    as_of = str(run.get("as_of_date") or "")
    rows = run.get("snapshot_rows", 0)
    return f"{as_of} | {rows} 檔 | {created_at}"


def _load_supabase_run(run_id: str) -> None:
    stored = load_backtest_snapshot(run_id)
    st.session_state[SUPABASE_LOADED_KEY] = {
        "snapshot": stored.snapshot,
        "diagnostics": stored.diagnostics,
        "run": stored.run,
    }


def render_summary(df_snapshot: pd.DataFrame, diagnostics: SnapshotDiagnostics) -> None:
    dragon_count = int(df_snapshot["is_dragon_rise_pass"].sum()) if "is_dragon_rise_pass" in df_snapshot.columns else 0
    hidden_count = int(df_snapshot["is_dragon_hidden_pass"].sum()) if "is_dragon_hidden_pass" in df_snapshot.columns else 0
    unique_count = (
        df_snapshot[df_snapshot["is_dragon_rise_pass"] | df_snapshot["is_dragon_hidden_pass"]]["stock_id"].nunique()
        if not df_snapshot.empty
        else 0
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("共用條件通過", f"{diagnostics.common_passed} 檔")
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
            {"項目": "共用條件通過", "數值": diagnostics.common_passed, "說明": "價量、營收、近四季 EPS 全部通過"},
            {"項目": "共用條件未通過", "數值": diagnostics.common_failed, "說明": "已完成 FinMind 查詢但 EPS 等共用門檻未通過"},
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
    st.divider()
    st.header("持有期績效")
    performance_end_date = st.date_input("績效結束日", value=taipei_today())
    performance_max_stocks = int(
        st.number_input(
            "最多計算檔數",
            value=30,
            min_value=0,
            step=10,
            help="0 代表計算全部入選股；檔數越多，FinMind 查詢時間越長。",
        )
    )
    run_btn = st.button("重建基準日選股池", use_container_width=True, type="primary")
    performance_btn = st.button("計算持有期績效", use_container_width=True)
    if st.button("清除本頁結果", use_container_width=True):
        for key in list(st.session_state):
            if str(key).startswith("double_dragon_backtest_snapshot:"):
                st.session_state.pop(key, None)
            if str(key).startswith("double_dragon_backtest_performance:"):
                st.session_state.pop(key, None)
        st.session_state.pop(SUPABASE_LOADED_KEY, None)
        st.success("已清除本頁快取結果。")
        st.stop()

    st.divider()
    st.header("Supabase 快照")
    supabase_status = get_supabase_status()
    if not supabase_status.configured:
        st.caption(supabase_status.message)
    else:
        st.caption("Supabase 已設定，可儲存與載入回測快照。")
        if st.button("重新整理快照清單", use_container_width=True):
            try:
                st.session_state[SUPABASE_RUNS_KEY] = list_backtest_runs(limit=20)
            except SupabaseBacktestStoreError as exc:
                st.warning(str(exc))
        runs = st.session_state.get(SUPABASE_RUNS_KEY, [])
        if runs:
            options = {run["run_id"]: _format_supabase_run(run) for run in runs}
            selected_run_id = st.selectbox(
                "最近快照",
                options=list(options),
                format_func=lambda run_id: options.get(run_id, run_id),
            )
            if st.button("載入選定快照", use_container_width=True):
                try:
                    _load_supabase_run(selected_run_id)
                    st.success("已載入 Supabase 快照。")
                    st.rerun()
                except SupabaseBacktestStoreError as exc:
                    st.error(str(exc))


key = _result_key(as_of_date, max_targets)

if run_btn:
    st.session_state.pop(SUPABASE_LOADED_KEY, None)
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

saved = st.session_state.get(key) or st.session_state.get(SUPABASE_LOADED_KEY)
if not saved:
    st.info("選擇基準日後，按下側邊欄的「重建基準日選股池」。第一版會先重建該日的雙龍選股池，不先計算持有期報酬。")
    st.stop()

df_snapshot = saved["snapshot"]
diagnostics = saved["diagnostics"]
loaded_run = saved.get("run", {})
display_as_of_date = loaded_run.get("as_of_date") or as_of_date

st.subheader(f"{display_as_of_date} 雙龍吐珠選股池")
render_summary(df_snapshot, diagnostics)
render_diagnostics(diagnostics)

with st.expander("Supabase 快照", expanded=False):
    supabase_status = get_supabase_status()
    if not supabase_status.configured:
        st.info("尚未設定 Supabase。請先建立 schema，並設定 SUPABASE_URL 與 SUPABASE_SERVICE_ROLE_KEY。")
        st.caption("Schema 檔案：backtest_data_layer/supabase_schema.sql")
    else:
        if loaded_run:
            st.caption(f"目前載入 run_id：{loaded_run.get('run_id', '')}")
        if st.button("存入 Supabase", disabled=df_snapshot.empty, use_container_width=True):
            try:
                run_id = save_backtest_snapshot(display_as_of_date, df_snapshot, diagnostics, max_targets=max_targets)
                st.success(f"已存入 Supabase：{run_id}")
                st.session_state.pop(SUPABASE_RUNS_KEY, None)
            except SupabaseBacktestStoreError as exc:
                st.error(str(exc))

if diagnostics.rate_limit_error:
    st.warning("FinMind 查詢受限，本次資料池不完整，請稍後重跑或提供 Token。")

if df_snapshot.empty:
    st.warning("本次沒有股票通過雙龍吐珠共用條件。請先查看資料重建診斷，確認是條件未通過，還是資料來源抓取不足。")
    st.stop()

dragon_df = df_snapshot[df_snapshot["is_dragon_rise_pass"]].copy()
hidden_df = df_snapshot[df_snapshot["is_dragon_hidden_pass"]].copy()
combined_df = df_snapshot[
    df_snapshot["is_dragon_rise_pass"] | df_snapshot["is_dragon_hidden_pass"]
].copy()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["龍騰升空", "潛龍在淵", "雙龍合併", "基準日明細", "持有期績效"])
date_token = pd.to_datetime(display_as_of_date).strftime("%Y%m%d")

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
    display_df = render_snapshot_table(df_snapshot, include_audit=True)
    render_download(display_df, "下載基準日明細 CSV", f"雙龍基準日明細_{date_token}.csv")

performance_key = _performance_key(display_as_of_date, performance_end_date, max_targets, performance_max_stocks)
if performance_btn:
    if pd.to_datetime(performance_end_date) <= pd.to_datetime(display_as_of_date):
        st.warning("績效結束日必須晚於基準日。")
        st.stop()
    performance_status = st.empty()
    performance_progress = st.progress(0, text="準備計算持有期績效...")

    def update_performance_progress(done: int, total: int, stock_id: str) -> None:
        ratio = min(done / total, 1.0) if total else 1.0
        performance_progress.progress(ratio, text=f"FinMind 歷史價格：{done} / {total}（{stock_id}）")

    try:
        performance_status.info("以基準日收盤價作為進場價，逐檔取得出場日前的可用收盤價。")
        return_df, curve_df, performance_kpis, performance_diagnostics = build_return_analysis(
            combined_df,
            display_as_of_date,
            performance_end_date,
            token=finmind_token,
            benchmark_id="TAIEX",
            max_stocks=performance_max_stocks,
            progress_callback=update_performance_progress,
        )
    except Exception as exc:
        performance_progress.empty()
        st.error(f"績效計算失敗：{type(exc).__name__}: {exc}")
        st.stop()
    performance_progress.progress(1.0, text="持有期績效計算完成")
    performance_status.empty()
    st.session_state[performance_key] = {
        "return_df": return_df,
        "curve_df": curve_df,
        "kpis": performance_kpis,
        "diagnostics": performance_diagnostics,
    }

with tab5:
    performance_result = st.session_state.get(performance_key)
    if not performance_result:
        st.info("按下側邊欄的「計算持有期績效」後，這裡會顯示個股報酬、大盤報酬、超額報酬、KPI 與曲線圖。")
    else:
        render_performance_kpis(performance_result["kpis"], performance_result["diagnostics"])
        render_performance_chart(performance_result["curve_df"])
        render_return_table(performance_result["return_df"], date_token)

st.caption(
    f"資料重建時間：{taipei_now().strftime('%Y-%m-%d %H:%M:%S')}。"
    "基準日價量來自 TWSE/TPEX 歷史行情；月營收來自 MOPS；MA60、六個月低點與 EPS 來自 FinMind；PE 以基準日收盤價 / 近四季 EPS 計算。"
)

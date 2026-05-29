import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from _finmind_api import (
    fetch_finmind_result,
    get_result_message,
    get_retry_after,
    get_status_code,
    is_rate_limited,
    parse_eps_dataframe,
    parse_price_dataframe,
)
from _market_data import build_latest_revenue_view, build_price_snapshot, build_revenue_snapshot
from _market_api import fetch_json_tpex as fetch_json_tpex_base, fetch_json_twse as fetch_json_twse_base

load_dotenv()


def build_alert_flags(result_df: pd.DataFrame, rev_growth_floor: float, rebound_ceiling: float) -> pd.DataFrame:
    result_df = result_df.copy()

    def _flags(row: pd.Series) -> str:
        flags = []
        rev_yoy = pd.to_numeric(row.get("rev_yoy"), errors="coerce")
        rebound_pct = pd.to_numeric(row.get("rebound_pct"), errors="coerce")
        latest_hist_vol_lot = pd.to_numeric(row.get("latest_hist_vol_lot"), errors="coerce")
        avg_vol_20 = pd.to_numeric(row.get("avg_vol_20"), errors="coerce")

        if pd.notna(rebound_pct) and rebound_pct <= 3:
            flags.append("貼近支撐")
        elif pd.notna(rebound_pct) and rebound_pct <= 8:
            flags.append("起漲初段")
        elif pd.notna(rebound_pct) and rebound_pct >= max(rebound_ceiling - 3, rebound_ceiling * 0.8):
            flags.append("空間縮小")

        if pd.notna(rev_yoy) and rev_yoy < max(rev_growth_floor + 5, 10):
            flags.append("營收轉弱")

        if (
            pd.notna(rebound_pct)
            and rebound_pct > 3
            and pd.notna(latest_hist_vol_lot)
            and pd.notna(avg_vol_20)
            and latest_hist_vol_lot < avg_vol_20
        ):
            flags.append("反彈無量")

        return "｜".join(flags) if flags else "正常"

    result_df["alert_flags"] = result_df.apply(_flags, axis=1)
    return result_df


def render_alert_summary(display_df: pd.DataFrame) -> None:
    alert_col = "警示標記" if "警示標記" in display_df.columns else "霅衣內璅?"
    if display_df.empty or alert_col not in display_df.columns:
        return

    flattened = "｜".join(display_df[alert_col].astype(str).tolist())
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("貼近支撐", flattened.count("貼近支撐"))
    col2.metric("起漲初段", flattened.count("起漲初段"))
    col3.metric("空間縮小", flattened.count("空間縮小"))
    col4.metric("營收轉弱", flattened.count("營收轉弱"))
    col5.metric("反彈無量", flattened.count("反彈無量"))

# ─────────────────────────────────────────────
# API 端點
# ─────────────────────────────────────────────
URL_TWSE_PRICE = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
URL_TWSE_REV = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
URL_TPEX_PRICE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
URL_TPEX_REV = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
from _app_common import FINMIND_URL
from _export_utils import dataframe_to_csv_bytes
from _page_bootstrap import ROOT_DIR

# ─────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────
st.set_page_config(page_title="底部剛起漲選股器", page_icon="📈", layout="wide")

from _style import apply_style, page_header, render_global_navigation

apply_style()
page_header("📈", "底部剛起漲選股器", "策略：近半年低點支撐 ｜ 漲幅未明顯 ｜ 營收年增為正")


def render_page_positioning() -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            """
            **這頁看什麼**

            找出近半年有明確支撐、股價剛離底不遠，且最新營收年增仍為正的股票。
            """
        )
    with col2:
        st.markdown(
            """
            **適合什麼情境**

            適合想先找「底部整理後開始轉強」標的，再進一步做人手複核的情境。
            """
        )
    with col3:
        st.markdown(
            """
            **篩選風格**

            邏輯屬於 **中性偏積極**，先過濾流動性與營收，再從底部型態中找起漲股。
            """
        )


render_page_positioning()


def render_strategy_card() -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("策略核心", "貼底轉強")
    col2.metric("支撐區間", "近半年低點")
    col3.metric("資料主體", "官方 + FinMind")
    col4.metric("判讀重點", "空間與量能")
    st.caption("先確認股價仍貼近支撐，再看營收是否維持正向，最後檢查反彈是否有量能配合。")


render_strategy_card()
st.caption("本頁優先處理底部型態、營收動能與短線技術位階，不直接等於買進訊號。")

# ─────────────────────────────────────────────
# 側邊欄
# ─────────────────────────────────────────────
with st.sidebar:
    render_global_navigation("bottom_screener")
    st.markdown("---")
    st.header("⚙️ 選股條件")
    st.divider()
    st.markdown("**資料設定**")
    finmind_token = st.text_input(
        "FinMind Token（選填）",
        value=os.getenv("FINMIND_TOKEN", ""),
        type="password",
        help="用於查詢通過前置條件股票的近半年歷史股價；估值改採官方上市櫃API。",
    ).strip()

    st.markdown("**核心條件**")
    support_months = int(st.number_input(
        "底部觀察月數", value=6, min_value=3, max_value=12, step=1,
        help="用近 N 個月最低價作為底部支撐價格。",
    ))
    rebound_max = st.number_input(
        "自底部起漲幅 小於等於（%）", value=15.0, min_value=0.0, max_value=100.0, step=1.0,
        help="最新收盤價相對近半年支撐價的漲幅；預設 15%。",
    )
    rev_growth_min = st.number_input(
        "月營收(單月) 年成長率 大於（%）", value=5.0, min_value=-100.0, max_value=1000.0, step=1.0,
        help="最新單月月營收年增率（去年同月增減%）。",
    )
    vol_min = st.number_input(
        "前一日成交量 至少（張）", value=500, min_value=0, step=100,
        help="使用 TWSE/TPEX 最新交易日成交量，單位為張。",
    )
    price_min = st.number_input(
        "股價 大於（元）", value=100.0, min_value=0.0, step=5.0,
        help="先剔除 100 元以下股票，降低低價股造成的候選數量。",
    )
    st.markdown("**操作**")
    run_btn = st.button("🔍 開始選股", use_container_width=True, type="primary")
    if st.button("🗑️ 清除快取（強制重新抓資料）", use_container_width=True):
        st.session_state.pop("bottom_screener_result", None)
        st.success("✅ 本頁結果已清除，請重新選股")
        st.stop()

    st.markdown("---")
    st.markdown("**資料來源**")
    st.caption("📡 股價/月營收：TWSE + TPEX OpenAPI（免費）")
    st.caption("📡 近半年歷史股價：FinMind TaiwanStockPrice（三線程查詢）")
    st.caption("📡 本益比：官方上市櫃 API")
    st.caption("📢 本系統僅供學術研究，不構成投資建議")


def parse_finmind_retry_seconds(error_msg: str):
    parts = str(error_msg).split(":", 2)
    if len(parts) < 2:
        return None
    try:
        return max(int(float(parts[1])), 0)
    except Exception:
        return None


def format_wait_time(seconds):
    if seconds is None:
        return "未知"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours} 小時 {minutes} 分 {sec} 秒"
    if minutes > 0:
        return f"{minutes} 分 {sec} 秒"
    return f"{sec} 秒"


def format_retry_at(seconds):
    if seconds is None:
        return "未知"
    retry_at = datetime.now() + timedelta(seconds=int(seconds))
    return retry_at.strftime("%H:%M:%S")


# ─────────────────────────────────────────────
# 說明頁 / 恢復上次結果
# ─────────────────────────────────────────────
def make_display_df(result_df: pd.DataFrame) -> pd.DataFrame:
    _rename = {
        "alert_flags": "警示標記",
        "stock_id": "股票代碼",
        "stock_name": "股票名稱",
        "market": "市場",
        "close": "收盤價(元)",
        "support_price": "近半年支撐價(元)",
        "support_date": "支撐日期",
        "rebound_pct": "自底部漲幅(%)",
        "vol_lot": "前一日成交量(張)",
        "rev_yoy": "單月營收年增率(%)",
        "rev_ym": "最新營收年月",
        "history_days": "歷史交易日數",
    }
    _cols = [
        "警示標記", "股票代碼", "股票名稱", "市場", "收盤價(元)", "近半年支撐價(元)", "支撐日期",
        "自底部漲幅(%)", "前一日成交量(張)", "單月營收年增率(%)", "最新營收年月", "歷史交易日數",
    ]
    display_df = result_df.rename(columns=_rename)[_cols]
    for col in ["收盤價(元)", "近半年支撐價(元)", "自底部漲幅(%)", "單月營收年增率(%)"]:
        display_df[col] = pd.to_numeric(display_df[col], errors="coerce").round(2)
    display_df["前一日成交量(張)"] = pd.to_numeric(
        display_df["前一日成交量(張)"], errors="coerce"
    ).fillna(0).round(0).astype(int)
    display_df["歷史交易日數"] = pd.to_numeric(
        display_df["歷史交易日數"], errors="coerce"
    ).fillna(0).round(0).astype(int)
    return display_df.sort_values(
        ["收盤價(元)", "自底部漲幅(%)"], ascending=[False, True]
    ).reset_index(drop=True)


def render_bottom_result_overview(display_df: pd.DataFrame, support_window_label: str) -> None:
    alert_col = "警示標記" if "警示標記" in display_df.columns else "霅衣內璅?"
    if display_df.empty or alert_col not in display_df.columns:
        return

    alerts = display_df[alert_col].astype(str)
    positive_count = alerts.str.contains("貼近支撐|起漲初段", regex=True).sum()
    risk_count = alerts.str.contains("空間縮小|營收轉弱|反彈無量", regex=True).sum()
    normal_count = (alerts == "正常").sum()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("候選檔數", f"{len(display_df)} 檔")
    col2.metric("正向訊號", int(positive_count))
    col3.metric("風險訊號", int(risk_count))
    col4.metric("正常觀察", int(normal_count), help=f"支撐區間：{support_window_label}")


def render_bottom_table(display_df: pd.DataFrame) -> None:
    alert_col = "警示標記" if "警示標記" in display_df.columns else "霅衣內璅?"
    code_col = "股票代碼" if "股票代碼" in display_df.columns else "?∠巨隞?Ⅳ"
    name_col = "股票名稱" if "股票名稱" in display_df.columns else "?∠巨?迂"
    market_col = "市場" if "市場" in display_df.columns else "撣"
    close_col = "收盤價(元)" if "收盤價(元)" in display_df.columns else "?嗥????"
    support_col = "近半年支撐價(元)" if "近半年支撐價(元)" in display_df.columns else "餈?撟湔?(??"
    support_date_col = "支撐日期" if "支撐日期" in display_df.columns else "?舀??交?"
    rebound_col = "自底部漲幅(%)" if "自底部漲幅(%)" in display_df.columns else "?芸??冽撞撟?%)"
    volume_col = "前一日成交量(張)" if "前一日成交量(張)" in display_df.columns else "???交?鈭日?(撘?"
    revenue_col = "單月營收年增率(%)" if "單月營收年增率(%)" in display_df.columns else "?格??撟游???%)"
    rev_month_col = "最新營收年月" if "最新營收年月" in display_df.columns else "??啁??嗅僑??"
    history_col = "歷史交易日數" if "歷史交易日數" in display_df.columns else "甇瑕鈭斗??交"

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            alert_col: st.column_config.TextColumn(alert_col, width="medium"),
            code_col: st.column_config.TextColumn(code_col, width="small"),
            name_col: st.column_config.TextColumn(name_col, width="medium"),
            market_col: st.column_config.TextColumn(market_col, width="small"),
            close_col: st.column_config.NumberColumn(close_col, format="%.2f"),
            support_col: st.column_config.NumberColumn(support_col, format="%.2f"),
            support_date_col: st.column_config.TextColumn(support_date_col, width="small"),
            rebound_col: st.column_config.NumberColumn(rebound_col, format="%.2f"),
            volume_col: st.column_config.NumberColumn(volume_col, format="%d"),
            revenue_col: st.column_config.NumberColumn(revenue_col, format="%.2f"),
            rev_month_col: st.column_config.TextColumn(rev_month_col, width="small"),
            history_col: st.column_config.NumberColumn(history_col, format="%d"),
        },
    )


if not run_btn:
    if "bottom_screener_result" in st.session_state:
        _r = st.session_state["bottom_screener_result"]
        st.info("💡 顯示上次選股結果。如需重新選股請點擊「開始選股」。")
        _disp = make_display_df(build_alert_flags(_r, rev_growth_min, rebound_max))
        st.subheader(f"📋 底部剛起漲名單（共 {len(_disp)} 檔）")
        _tab_summary, _tab_table, _tab_diag = st.tabs(["結果總覽", "明細表", "診斷與資料"])
        with _tab_summary:
            render_bottom_result_overview(_disp, f"{support_months} 個月")
            render_alert_summary(_disp)
        with _tab_table:
            render_bottom_table(_disp)
        with _tab_diag:
            st.caption("這是上次執行結果；若要更新資料，請重新執行篩選。")
            st.caption("資料來源：股價/月營收來自 TWSE + TPEX OpenAPI；歷史股價來自 FinMind TaiwanStockPrice。")
        _csv = dataframe_to_csv_bytes(_disp)
        st.download_button(
            "⬇️ 下載 CSV（Excel 可直接開啟）", _csv,
            f"底部剛起漲選股_{datetime.today().strftime('%Y%m%d')}.csv", "text/csv",
        )
        st.stop()

    st.info("👈 請在左側設定條件後，點擊「開始選股」")
    with st.expander("📖 選股條件與算法說明", expanded=True):
        st.markdown(f"""
| 條件 | 設定值 | 資料來源 |
|------|--------|---------|
| 底部支撐價 | 近 **{support_months}** 個月最低價 | FinMind TaiwanStockPrice |
| 自底部起漲幅 | ≤ **{rebound_max:.0f}%** | 最新收盤價 / 支撐價 - 1 |
| 股價 | > **{price_min:.0f}** 元 | TWSE/TPEX OpenAPI（免費） |
| 前一日成交量 | ≥ **{int(vol_min):,}** 張 | TWSE/TPEX OpenAPI（免費） |
| 月營收(單月)年成長率 | > **{rev_growth_min:.0f}%** | TWSE/TPEX OpenAPI（免費） |
**策略邏輯：**

先剔除 100 元以下股票，再用成交量與月營收年增率篩出基本流動性與營收仍正向的股票，
再查詢候選股近 {support_months} 個月歷史價格，以期間最低價作為底部支撐價，
通過起漲幅條件後留下仍具技術面底部型態的股票。

> 通過股價、成交量與營收條件的候選股會直接進入近半年支撐價篩選。
""")
    st.stop()

# ─────────────────────────────────────────────
# 共用函式
# ─────────────────────────────────────────────
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_json_twse(url: str) -> list:
    return fetch_json_twse_base(url)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_json_tpex(url: str) -> list:
    return fetch_json_tpex_base(url)


@st.cache_data(ttl=86400, show_spinner=False)
def get_finmind_price_history(symbol: str, start_date: str, end_date: str, token: str = "") -> pd.DataFrame:
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": start_date,
        "end_date": end_date,
    }
    if token:
        params["token"] = token

    time.sleep(1.2)
    result = fetch_finmind_result(params, timeout=30)
    status = result.get("status")
    msg = get_result_message(result)
    status_code = get_status_code(result)

    if is_rate_limited(result):
        raise RuntimeError(f"FINMIND_BANNED:{get_retry_after(result)}:{msg}")
    if status_code != 200 or not result.get("data"):
        return pd.DataFrame()

    df = parse_price_dataframe(result)
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "low", "close"]).sort_values("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


@st.cache_data(ttl=86400, show_spinner=False)
def get_finmind_last_yr_eps(symbol: str, token: str = "") -> float | None:
    """查詢去年全年EPS（最近完整4季年度加總）。rate-limit 時拋出 RuntimeError。"""
    start_year = datetime.today().year - 3
    params = {
        "dataset": "TaiwanStockFinancialStatements",
        "data_id": symbol,
        "start_date": f"{start_year}-01-01",
        "end_date": datetime.today().strftime("%Y-%m-%d"),
    }
    if token:
        params["token"] = token

    time.sleep(1.2)
    result = fetch_finmind_result(params, timeout=20)
    status = result.get("status")
    msg = get_result_message(result)
    status_code = get_status_code(result)

    if is_rate_limited(result):
        raise RuntimeError(f"FINMIND_BANNED:{get_retry_after(result)}:{msg}")
    if status_code != 200 or not result.get("data"):
        return None

    df = parse_eps_dataframe(result)
    if df.empty:
        return None
    df["year"] = df["date"].dt.year
    cur_year = datetime.today().year
    for yr in sorted(df["year"].unique(), reverse=True):
        if yr >= cur_year:
            continue
        yr_data = df[df["year"] == yr]
        if len(yr_data) >= 4:
            return float(yr_data["eps"].sum())
    return None


def calc_bottom_support(row: pd.Series, history_df: pd.DataFrame):
    if history_df.empty or len(history_df) < 60:
        return None
    history_df = history_df.sort_values("date").reset_index(drop=True).copy()
    history_df["vol_lot_hist"] = pd.to_numeric(history_df["volume"], errors="coerce") / 1000
    recent_window = history_df.tail(60).dropna(subset=["low"]).copy()
    if recent_window.empty:
        return None

    # Use a robust recent support level to avoid one-day tail-risk lows dominating the signal.
    support_price = float(pd.to_numeric(recent_window["low"], errors="coerce").quantile(0.15))
    if support_price <= 0:
        return None
    support_touches = recent_window[recent_window["low"] <= support_price * 1.03]
    support_row = support_touches.iloc[-1] if not support_touches.empty else recent_window.loc[recent_window["low"].idxmin()]
    latest_close = float(row["close"])
    rebound_pct = (latest_close / support_price - 1) * 100
    latest_row = history_df.iloc[-1]
    return {
        "stock_id": row["stock_id"],
        "stock_name": row["stock_name"],
        "market": row["market"],
        "close": latest_close,
        "vol_lot": float(row["vol_lot"]),
        "rev_yoy": float(row["rev_yoy"]),
        "rev_ym": row["rev_ym"],
        "rev_cur": row["rev_cur"],
        "rev_ly": row["rev_ly"],
        "support_price": support_price,
        "support_date": pd.to_datetime(support_row["date"]).strftime("%Y-%m-%d"),
        "rebound_pct": rebound_pct,
        "history_days": len(history_df),
        "avg_vol_20": float(history_df["vol_lot_hist"].tail(20).mean()) if history_df["vol_lot_hist"].tail(20).notna().any() else None,
        "latest_hist_vol_lot": float(latest_row["vol_lot_hist"]) if pd.notna(latest_row["vol_lot_hist"]) else None,
    }


def build_alert_flags(result_df: pd.DataFrame, rev_growth_floor: float, rebound_ceiling: float) -> pd.DataFrame:
    result_df = result_df.copy()

    def _flags(row: pd.Series) -> str:
        flags = []
        rev_yoy = pd.to_numeric(row.get("rev_yoy"), errors="coerce")
        rebound_pct = pd.to_numeric(row.get("rebound_pct"), errors="coerce")
        latest_hist_vol_lot = pd.to_numeric(row.get("latest_hist_vol_lot"), errors="coerce")
        avg_vol_20 = pd.to_numeric(row.get("avg_vol_20"), errors="coerce")

        if pd.notna(rebound_pct) and rebound_pct <= 3:
            flags.append("貼近支撐")
        elif pd.notna(rebound_pct) and rebound_pct <= 8:
            flags.append("起漲初段")
        elif pd.notna(rebound_pct) and rebound_pct >= max(rebound_ceiling - 3, rebound_ceiling * 0.8):
            flags.append("空間縮小")

        if pd.notna(rev_yoy) and rev_yoy < max(rev_growth_floor + 5, 10):
            flags.append("營收轉弱")

        if (
            pd.notna(rebound_pct)
            and rebound_pct > 3
            and pd.notna(latest_hist_vol_lot)
            and pd.notna(avg_vol_20)
            and latest_hist_vol_lot < avg_vol_20
        ):
            flags.append("反彈無量")

        return "｜".join(flags) if flags else "正常"

    result_df["alert_flags"] = result_df.apply(_flags, axis=1)
    return result_df


def render_alert_summary(display_df: pd.DataFrame) -> None:
    if display_df.empty or "警示標記" not in display_df.columns:
        return

    flattened = "｜".join(display_df["警示標記"].astype(str).tolist())
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("貼近支撐", flattened.count("貼近支撐"))
    col2.metric("起漲初段", flattened.count("起漲初段"))
    col3.metric("空間縮小", flattened.count("空間縮小"))
    col4.metric("營收轉弱", flattened.count("營收轉弱"))
    col5.metric("反彈無量", flattened.count("反彈無量"))


# ─────────────────────────────────────────────
# Step 1：抓取最新股價與月營收
# ─────────────────────────────────────────────
progress = st.progress(0, text="🚀 準備中...")

progress.progress(8, text="📈 取得上市股價（TWSE）...")
try:
    raw_twse_price = fetch_json_twse(URL_TWSE_PRICE)
except Exception as e:
    st.error(f"❌ 上市股價 API 失敗：{e}")
    st.stop()

progress.progress(16, text="📈 取得上櫃股價（TPEX）...")
try:
    raw_tpex_price = fetch_json_tpex(URL_TPEX_PRICE)
except Exception as e:
    st.error(f"❌ 上櫃股價 API 失敗：{e}")
    st.stop()

progress.progress(24, text="💰 取得上市月營收（TWSE）...")
try:
    raw_twse_rev = fetch_json_twse(URL_TWSE_REV)
except Exception as e:
    st.error(f"❌ 上市月營收 API 失敗：{e}")
    st.stop()

progress.progress(32, text="💰 取得上櫃月營收（TPEX）...")
try:
    raw_tpex_rev = fetch_json_tpex(URL_TPEX_REV)
except Exception as e:
    st.error(f"❌ 上櫃月營收 API 失敗：{e}")
    st.stop()

progress.progress(40, text="🔧 整理股價與月營收資料...")

# ─────────────────────────────────────────────
# Step 2：整理股價與成交量
# ─────────────────────────────────────────────
df_price = build_price_snapshot(raw_twse_price, raw_tpex_price)

df_price_filtered = df_price[
    (df_price["close"] > price_min) & (df_price["vol_lot"] >= vol_min)
].copy().reset_index(drop=True)

# ─────────────────────────────────────────────
# Step 3：整理最新單月營收
# ─────────────────────────────────────────────
df_rev = build_revenue_snapshot(raw_twse_rev, raw_tpex_rev)
df_rev_latest = build_latest_revenue_view(df_rev)

# ─────────────────────────────────────────────
# Step 4：免費資料前置篩選
# ─────────────────────────────────────────────
df_merged = df_price_filtered.merge(
    df_rev_latest[["stock_id", "rev_ym", "rev_yoy", "rev_cur", "rev_ly"]],
    on="stock_id", how="inner",
)
df_candidates = df_merged[df_merged["rev_yoy"] > rev_growth_min].copy().reset_index(drop=True)
n_candidates = len(df_candidates)

progress.progress(50, text=f"📊 成交量+營收通過 {n_candidates} 檔，準備查詢近半年歷史股價...")

if n_candidates == 0:
    progress.progress(100, text="✅ 完成")
    st.warning("⚠️ 沒有股票通過成交量與月營收條件，請放寬設定。")
    st.stop()

df_history_targets = df_candidates.sort_values(
    ["rev_yoy", "vol_lot"], ascending=[False, False]
).reset_index(drop=True)

st.caption(
    f"通過股價、成交量與營收條件的 {len(df_history_targets)} 檔，將再查詢近半年歷史股價。"
)

# ─────────────────────────────────────────────
# Step 5：三線程查詢近半年歷史股價並計算支撐價
# ─────────────────────────────────────────────
end_date = datetime.today().date()
start_date = end_date - timedelta(days=int(support_months * 31))
start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

n_targets = len(df_history_targets)
history_bar = st.progress(0, text=f"🔍 三線程查詢近 {support_months} 個月歷史股價（0 / {n_targets} 檔）...")
support_rows = []
history_failed = []
_banned_msg = ""


def fetch_support_row(row: pd.Series):
    sid = str(row["stock_id"])
    try:
        hist = get_finmind_price_history(sid, start_str, end_str, finmind_token)
        support_row = calc_bottom_support(row, hist)
        if support_row is None:
            return "failed", sid
        return "ok", support_row
    except RuntimeError as e:
        err = str(e)
        if "FINMIND_BANNED" in err:
            return "banned", err
        return "failed", sid
    except Exception:
        return "failed", sid


done_count = 0
with ThreadPoolExecutor(max_workers=3) as executor:
    futures = [
        executor.submit(fetch_support_row, row)
        for _, row in df_history_targets.iterrows()
    ]

    for future in as_completed(futures):
        status, payload = future.result()
        done_count += 1

        if status == "ok":
            support_rows.append(payload)
        elif status == "banned":
            _banned_msg = payload
            for pending in futures:
                pending.cancel()
            break
        else:
            history_failed.append(payload)

        history_bar.progress(
            min(done_count / n_targets, 1.0),
            text=f"🔍 三線程查詢近 {support_months} 個月歷史股價（{done_count} / {n_targets} 檔）...",
        )

if _banned_msg and not support_rows:
    _retry_seconds = parse_finmind_retry_seconds(_banned_msg)
    history_bar.progress(1.0, text="❌ FinMind IP 封鎖")
    st.error(
        f"❌ FinMind API 回傳 **IP 暫時封鎖**（ip banned）\n\n"
        f"剩餘等待時間：約 **{format_wait_time(_retry_seconds)}**\n\n"
        f"預估可重新查詢時間：**{format_retry_at(_retry_seconds)}**\n\n"
        f"本次尚未完成可用的歷史股價查詢，請稍後再試。"
    )
    st.stop()

if _banned_msg and support_rows:
    _retry_seconds = parse_finmind_retry_seconds(_banned_msg)
    st.warning(
        f"⚠️ FinMind API 中途被 rate limit，僅完成 {len(support_rows)} / {n_targets} 檔可用歷史股價。"
        f"剩餘等待時間：約 **{format_wait_time(_retry_seconds)}**；"
        f"預估可重新查詢時間：**{format_retry_at(_retry_seconds)}**。"
    )

history_bar.progress(1.0, text="✅ 歷史股價查詢完成")

df_support = pd.DataFrame(support_rows)
if df_support.empty:
    progress.progress(100, text="✅ 完成")
    st.warning("⚠️ 歷史股價資料不足，無法計算近半年支撐價。請稍後再試或降低前置條件。")
    st.stop()

df_result = df_support[
    (df_support["rebound_pct"] >= 0) & (df_support["rebound_pct"] <= rebound_max)
].copy().reset_index(drop=True)

# ─────────────────────────────────────────────
# Step 6：估值篩選已移除
# ─────────────────────────────────────────────
if df_result.empty:
    pass  # 無候選股，跳過 EPS 查詢

progress.progress(100, text="✅ 選股完成！")
st.session_state["bottom_screener_result"] = df_result

# ─────────────────────────────────────────────
# 顯示結果
# ─────────────────────────────────────────────
count = len(df_result)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("符合條件", f"{count} 檔")
col2.metric("底部起漲幅", f"≤ {rebound_max:.0f}%")
col3.metric("成交量", f"≥ {int(vol_min):,} 張")
col4.metric("月營收年增", f"> {rev_growth_min:.0f}%")
col5.metric("股價", f"> {price_min:.0f} 元")

st.divider()

_diag = df_support[[
    "stock_id", "stock_name", "market", "close", "support_price", "support_date",
    "rebound_pct", "vol_lot", "rev_yoy", "rev_ym", "history_days",
    "avg_vol_20", "latest_hist_vol_lot",
]].copy()
_diag = make_display_df(build_alert_flags(_diag, rev_growth_min, rebound_max))

if count == 0:
    st.warning(
        f"⚠️ 已成功計算 {len(df_support)} 檔支撐價，但自底部起漲幅 ≤ {rebound_max:.0f}% 後無符合。"
    )
    with st.expander("查看篩選流程診斷", expanded=False):
        st.write(
            f"成交量+營收通過：{n_candidates} 檔｜"
            f"歷史股價查詢：{n_targets} 檔｜"
            f"可計算支撐價：{len(df_support)} 檔｜"
            f"歷史資料不足/失敗：{len(history_failed)} 檔"
        )
        st.caption("以下為已成功計算近半年支撐價的股票，包含未通過起漲幅條件者。")
        st.dataframe(_diag, use_container_width=True, hide_index=True)
    _near = df_support.sort_values(["close", "rebound_pct"], ascending=[False, True]).head(20)
    if not _near.empty:
        with st.expander("查看距離底部支撐較近的候選股", expanded=False):
            st.dataframe(
                make_display_df(build_alert_flags(_near, rev_growth_min, rebound_max)),
                use_container_width=True,
                hide_index=True,
            )
    st.stop()

_data_date_caption = ""
try:
    _price_date_raw = raw_twse_price[0].get("Date", "")
    if len(_price_date_raw) == 7:
        _py, _pm, _pd = int(_price_date_raw[:3]) + 1911, _price_date_raw[3:5], _price_date_raw[5:7]
        _date_str = f"{_py}/{_pm}/{_pd}"
    else:
        _date_str = _price_date_raw
    _data_date_caption = (
        f"📅 最新股價/成交量資料日期：{_date_str}（TWSE 最近交易日）"
        f"｜支撐價計算區間：{start_str} ~ {end_str}"
    )
except Exception:
    pass

display_df = make_display_df(build_alert_flags(df_result, rev_growth_min, rebound_max))
st.subheader(f"📋 底部剛起漲名單（共 {count} 檔，以收盤價降冪排序）")
tab_summary, tab_table, tab_diag = st.tabs(["結果總覽", "明細表", "診斷與資料"])
with tab_summary:
    render_bottom_result_overview(display_df, f"{support_months} 個月")
    render_alert_summary(display_df)
with tab_table:
    render_bottom_table(display_df)
with tab_diag:
    if _data_date_caption:
        st.caption(_data_date_caption)
    st.write(
        f"成交量+營收通過：{n_candidates} 檔｜"
        f"歷史股價查詢：{n_targets} 檔｜"
        f"可計算支撐價：{len(df_support)} 檔｜"
        f"歷史資料不足/失敗：{len(history_failed)} 檔"
    )
    st.caption("以下為已成功計算近半年支撐價的股票，包含未通過起漲幅條件者。")
    st.dataframe(_diag, use_container_width=True, hide_index=True)
    st.caption("資料來源：股價/月營收來自 TWSE + TPEX OpenAPI；歷史股價來自 FinMind TaiwanStockPrice。")

csv = dataframe_to_csv_bytes(display_df)
st.download_button(
    "⬇️ 下載 CSV（Excel 可直接開啟）", csv,
    f"底部剛起漲選股_{datetime.today().strftime('%Y%m%d')}.csv", "text/csv",
)

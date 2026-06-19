import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from data_layer.data_diagnostics import (
    DataSourceDiagnostic,
    STATUS_COMPLETE,
    STATUS_FAILED,
    fetch_json_with_diagnostic,
    make_finmind_diagnostic,
)
from data_layer.historical_price_service import clean_price_history, fetch_cached_finmind_price_history
from data_layer.market_data import build_latest_revenue_view, build_price_snapshot
from data_layer.mops_revenue import fetch_mops_recent_revenue_frame, latest_revenue_ym
from data_layer.market_api import (
    fetch_json_tpex as fetch_json_tpex_base,
    fetch_latest_twse_price_rows,
)
from data_layer.app_common import get_runtime_secret
from data_layer.time_utils import taipei_now, taipei_today
from data_layer.portfolio_store import get_default_family_id
from data_layer.public_valuation import attach_public_valuation, fetch_public_pe_ratios_with_diagnostics
from render_layer.diagnostics import render_data_diagnostics
from render_layer.watchlist import format_watchlist_number, render_watchlist_adder as render_watchlist_adder_base

load_dotenv()

RESULT_VIEW_OPTIONS = ["標記說明", "明細表", "診斷與資料"]
FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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


def render_bottom_tag_explainer(
    support_months: int,
    rebound_max: float,
    rev_growth_min: float,
    price_min: float,
    vol_min: int,
) -> None:
    st.markdown(
        f"""
**標記說明（實際邏輯）**

- 先通過主條件後才會進入候選或結果：
  - 股價 `> {price_min:.0f}`、成交量 `>= {int(vol_min):,}`、單月營收年增 `> {rev_growth_min:.0f}%`
  - 支撐價以近約 `{support_months}` 個月資料計算（程式使用最近60交易日 low 的 15% 分位）
  - 結果名單再限制：`自底部漲幅` 需在 `0% ~ {rebound_max:.0f}%`

| 標記 | 觸發條件（對應程式） |
|---|---|
| 貼近支撐 | `rebound_pct <= 3` |
| 起漲初段 | `3 < rebound_pct <= 8` |
| 空間縮小 | `rebound_pct >= max(反彈上限-3, 反彈上限×0.8)` |
| 營收轉弱 | `rev_yoy < max(營收門檻+5, 10)` |
| 反彈無量 | `rebound_pct > 3` 且 `latest_hist_vol_lot < avg_vol_20` |
| 正常 | 以上標記皆未觸發 |
"""
    )
    st.caption("欄位對應：rebound_pct=自底部漲幅、latest_hist_vol_lot=最新一日歷史量(張)、avg_vol_20=近20日均量(張)。")

# ─────────────────────────────────────────────
# API 端點
# ─────────────────────────────────────────────
URL_TPEX_PRICE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
from data_layer.export_utils import dataframe_to_csv_bytes

# ─────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────
st.set_page_config(page_title="底部剛起漲選股器", page_icon="📈", layout="wide")

from render_layer.style import apply_style, page_header, render_global_navigation

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
    st.markdown("**自選股設定**")
    st.text_input(
        "family_id",
        value=st.session_state.get("inventory_family_id", get_default_family_id()),
        key="inventory_family_id",
        help="加入自選股時會寫入這組 family_id，與庫存股頁共用。",
    )
    st.divider()
    st.header("⚙️ 選股條件")
    st.divider()
    st.markdown("**資料設定**")
    finmind_token = st.text_input(
        "FinMind Token（選填）",
        value=get_runtime_secret("FINMIND_TOKEN", ""),
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
        st.cache_data.clear()
        st.session_state.pop("bottom_screener_result", None)
        st.success("✅ 本頁結果已清除，請重新選股")
        st.stop()

    st.markdown("---")
    st.markdown("**資料來源**")
    st.caption("📡 股價：TWSE + TPEX OpenAPI（免費）；月營收：MOPS")
    st.caption("📡 近半年歷史股價：FinMind TaiwanStockPrice（三線程查詢）")
    st.caption("📡 本益比：官方上市櫃 API")
    st.caption("📢 本系統僅供學術研究，不構成投資建議")


def parse_finmind_retry_seconds(error_msg: str):
    parts = str(error_msg).split(":", 3)
    numeric_parts = []
    for part in parts[1:]:
        try:
            numeric_parts.append(max(int(float(part)), 0))
        except Exception:
            continue
    if not numeric_parts:
        return None
    return numeric_parts[1] if len(numeric_parts) >= 2 else numeric_parts[0]


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
    retry_at = taipei_now() + timedelta(seconds=int(seconds))
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
            alert_col: st.column_config.TextColumn(alert_col, width=146),
            code_col: st.column_config.TextColumn(code_col, width=74),
            name_col: st.column_config.TextColumn(name_col, width=108),
            market_col: st.column_config.TextColumn(market_col, width=64),
            close_col: st.column_config.NumberColumn(close_col, width=92, format="%.2f"),
            support_col: st.column_config.NumberColumn(support_col, width=124, format="%.2f"),
            support_date_col: st.column_config.TextColumn(support_date_col, width=96),
            rebound_col: st.column_config.NumberColumn(rebound_col, width=116, format="%.2f"),
            volume_col: st.column_config.NumberColumn(volume_col, width=130, format="%d"),
            revenue_col: st.column_config.NumberColumn(revenue_col, width=138, format="%.2f"),
            rev_month_col: st.column_config.TextColumn(rev_month_col, width=104),
            history_col: st.column_config.NumberColumn(history_col, width=104, format="%d"),
        },
    )


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


@st.cache_data(ttl=1800, show_spinner=False)
def get_bottom_watchlist_chart_data(symbol: str, token: str = "") -> pd.DataFrame:
    today = taipei_today()
    start_date = (today - timedelta(days=220)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    try:
        df, status_code, _msg, _retry_after = fetch_cached_finmind_price_history(
            symbol,
            start_date,
            end_date,
            token=token,
            timeout=30,
            sleep_seconds=0,
            raise_on_rate_limit=False,
        )
        if status_code != 200 or df.empty:
            return pd.DataFrame()
        df = clean_price_history(df, required_columns=("date", "close"))
        return df.tail(120).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def render_watchlist_adder(result_df: pd.DataFrame, family_id: str, finmind_token: str = "") -> None:
    def _label(row: pd.Series) -> str:
        return (
            f"{row['stock_id']} {row['stock_name']} | {row['market']} | "
            f"收盤 {format_watchlist_number(row['close'])} | "
            f"營收年增 {format_watchlist_number(row['rev_yoy'], '%')} | "
            f"支撐價 {format_watchlist_number(row['support_price'])}"
        )

    def _caption(selected: dict, chart_df: pd.DataFrame) -> str:
        selected_close = pd.to_numeric(selected.get("close"), errors="coerce")
        selected_support = pd.to_numeric(selected.get("support_price"), errors="coerce")
        latest_ma60 = pd.to_numeric(chart_df["ma60"].iloc[-1], errors="coerce") if not chart_df.empty else None
        rebound = ((selected_close / selected_support) - 1) * 100 if pd.notna(selected_close) and pd.notna(selected_support) and selected_support else None
        return (
            f"目前收盤 {format_watchlist_number(selected_close)}｜"
            f"MA60 {format_watchlist_number(latest_ma60)}｜"
            f"距支撐價反彈 {format_watchlist_number(rebound, '%')}"
        )

    def _support_line(selected: dict):
        return pd.to_numeric(selected.get("support_price"), errors="coerce")

    render_watchlist_adder_base(
        result_df,
        family_id,
        select_columns=["stock_id", "stock_name", "market", "close", "rev_yoy", "support_price"],
        numeric_columns=["close", "rev_yoy", "support_price"],
        label_builder=_label,
        chart_loader=get_bottom_watchlist_chart_data,
        selectbox_key="bottom_watchlist_symbol",
        add_button_key="bottom_watchlist_add",
        finmind_token=finmind_token,
        caption_builder=_caption,
        support_line_builder=_support_line,
    )


family_id = st.session_state.get("inventory_family_id", get_default_family_id()).strip()
if not FAMILY_ID_PATTERN.fullmatch(family_id):
    st.error("family_id 格式錯誤，僅能使用英文字母、數字、底線(_)或連字號(-)，長度 1-64。")
    st.stop()


if not run_btn:
    if "bottom_screener_result" in st.session_state:
        _r = st.session_state["bottom_screener_result"]
        st.info("💡 顯示上次選股結果。如需重新選股請點擊「開始選股」。")
        _disp = make_display_df(build_alert_flags(_r, rev_growth_min, rebound_max))
        st.subheader(f"📋 底部剛起漲名單（共 {len(_disp)} 檔）")
        _view = render_result_view_selector("bottom_result_view")
        if _view == "標記說明":
            render_alert_summary(_disp)
            render_bottom_tag_explainer(support_months, rebound_max, rev_growth_min, price_min, int(vol_min))
        elif _view == "明細表":
            render_bottom_table(_disp)
            render_watchlist_adder(_r, family_id, finmind_token)
        else:
            st.caption("這是上次執行結果；若要更新資料，請重新執行篩選。")
            st.caption("資料來源：股價來自 TWSE + TPEX OpenAPI；月營收來自 MOPS；歷史股價來自 FinMind TaiwanStockPrice。")
        _csv = dataframe_to_csv_bytes(_disp)
        st.download_button(
            "⬇️ 下載 CSV（Excel 可直接開啟）", _csv,
            f"底部剛起漲選股_{taipei_now().strftime('%Y%m%d')}.csv", "text/csv",
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
| 月營收(單月)年成長率 | > **{rev_growth_min:.0f}%** | MOPS 月營收 |
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
def fetch_json_tpex(url: str) -> list:
    return fetch_json_tpex_base(url)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_mops_recent_revenue(latest_ym: str, months: int) -> pd.DataFrame:
    return fetch_mops_recent_revenue_frame(latest_ym, months=months)


@st.cache_data(ttl=86400, show_spinner=False)
def get_finmind_price_history(symbol: str, start_date: str, end_date: str, token: str = "") -> pd.DataFrame:
    df, status_code, msg, retry_after = fetch_cached_finmind_price_history(
        symbol,
        start_date,
        end_date,
        token=token,
        timeout=30,
        sleep_seconds=1.2,
        raise_on_rate_limit=False,
    )
    if status_code in (402, 403, 429):
        raise RuntimeError(f"FINMIND_LIMIT:{status_code}:{retry_after}:{msg}")
    if status_code != 200 or df.empty:
        return pd.DataFrame()
    df = clean_price_history(df, required_columns=("date", "low", "close"))
    return df[["date", "open", "high", "low", "close", "volume"]]


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


# ─────────────────────────────────────────────
# Step 1：抓取最新股價與月營收
# ─────────────────────────────────────────────
progress = st.progress(0, text="🚀 準備中...")
data_diagnostics = []

progress.progress(8, text="📈 取得上市股價（TWSE）...")
raw_twse_price, _diag = fetch_json_with_diagnostic(fetch_latest_twse_price_rows, "", "TWSE 股價")
data_diagnostics.append(_diag)

progress.progress(16, text="📈 取得上櫃股價（TPEX）...")
raw_tpex_price, _diag = fetch_json_with_diagnostic(fetch_json_tpex, URL_TPEX_PRICE, "TPEX 股價")
data_diagnostics.append(_diag)

_latest_rev_ym = latest_revenue_ym()
progress.progress(24, text=f"💰 取得 MOPS 月營收（{_latest_rev_ym} 起近 2 月）...")
try:
    df_rev = fetch_mops_recent_revenue(_latest_rev_ym, months=2)
    data_diagnostics.append(
        DataSourceDiagnostic(
            source="MOPS 月營收",
            status=STATUS_COMPLETE if not df_rev.empty else STATUS_FAILED,
            message="抓取成功。" if not df_rev.empty else "MOPS 月營收回傳空資料。",
            records=len(df_rev),
        )
    )
except Exception as exc:
    df_rev = pd.DataFrame()
    data_diagnostics.append(
        DataSourceDiagnostic(
            source="MOPS 月營收",
            status=STATUS_FAILED,
            message="抓取失敗，已將本資料源標記為不可用。",
            detail=f"{type(exc).__name__}: {exc}",
            records=0,
        )
    )

render_data_diagnostics(data_diagnostics, expanded=any(item.status != "complete" for item in data_diagnostics))

if not raw_twse_price and not raw_tpex_price:
    st.error("TWSE/TPEX 股價資料都無法取得，本頁無法產生可信選股結果。")
    st.stop()
if df_rev.empty:
    st.error("MOPS 月營收資料無法取得，本頁無法產生可信選股結果。")
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

progress.progress(52, text="取得官方 PE 並計算近 4 季 EPS...")
df_public_pe, pe_diagnostics = fetch_public_pe_ratios_with_diagnostics()
data_diagnostics.extend(pe_diagnostics)
if df_public_pe.empty:
    progress.progress(100, text="完成")
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.error("官方 PE 資料暫時無法取得，無法計算近 4 季 EPS。")
    st.stop()

df_candidates = attach_public_valuation(df_candidates, df_public_pe)
df_candidates = df_candidates[
    pd.to_numeric(df_candidates["ttm_eps"], errors="coerce") > 3
].copy().reset_index(drop=True)
n_candidates = len(df_candidates)

if n_candidates == 0:
    progress.progress(100, text="完成")
    st.warning("沒有股票通過近 4 季 EPS > 3 的門檻，請放寬篩選條件。")
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
end_date = taipei_today()
start_date = end_date - timedelta(days=int(support_months * 31))
start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

n_targets = len(df_history_targets)
history_bar = st.progress(0, text=f"🔍 三線程查詢近 {support_months} 個月歷史股價（0 / {n_targets} 檔）...")
support_rows = []
history_failed = []
_banned_msg = ""


def fetch_support_row(row_data: dict):
    sid = str(row_data["stock_id"])
    try:
        hist = get_finmind_price_history(sid, start_str, end_str, finmind_token)
        support_row = calc_bottom_support(pd.Series(row_data), hist)
        if support_row is None:
            return "failed", sid
        return "ok", support_row
    except RuntimeError as e:
        err = str(e)
        if "FINMIND_LIMIT" in err:
            return "banned", err
        return "failed", sid
    except Exception:
        return "failed", sid




done_count = 0
row_iter = iter(df_history_targets.to_dict("records"))
pending: dict = {}

with ThreadPoolExecutor(max_workers=3) as executor:
    for _ in range(min(3, n_targets)):
        try:
            row_data = next(row_iter)
        except StopIteration:
            break
        future = executor.submit(fetch_support_row, row_data)
        pending[future] = str(row_data["stock_id"])

    while pending:
        done, _not_done = wait(list(pending.keys()), return_when=FIRST_COMPLETED)

        for future in done:
            sid = pending.pop(future, "")
            status, payload = future.result()
            done_count += 1

            if status == "ok":
                support_rows.append(payload)
            elif status == "banned":
                _banned_msg = payload
            else:
                history_failed.append(payload or sid)

            history_bar.progress(
                min(done_count / n_targets, 1.0),
                text=f"🔍 三線程查詢近 {support_months} 個月歷史股價（{done_count} / {n_targets} 檔）...",
            )

            if _banned_msg:
                break

            try:
                row_data = next(row_iter)
            except StopIteration:
                continue
            next_future = executor.submit(fetch_support_row, row_data)
            pending[next_future] = str(row_data["stock_id"])

        if _banned_msg:
            for future in pending:
                future.cancel()
            break
if _banned_msg and not support_rows:
    _retry_seconds = parse_finmind_retry_seconds(_banned_msg)
    history_bar.progress(1.0, text="❌ FinMind IP 封鎖")
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 近半年歷史股價",
            429,
            _banned_msg,
            records=0,
            sample_ids=history_failed[:10],
        )
    )
    render_data_diagnostics(data_diagnostics, expanded=True)
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

if _banned_msg:
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 近半年歷史股價",
            429,
            _banned_msg,
            records=len(support_rows),
            sample_ids=history_failed[:10],
        )
    )
elif history_failed:
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 近半年歷史股價",
            None,
            "部分股票歷史股價不足或抓取失敗。",
            records=len(support_rows),
            sample_ids=history_failed[:10],
        )
    )
else:
    data_diagnostics.append(
        make_finmind_diagnostic("FinMind 近半年歷史股價", 200, "", records=len(support_rows))
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
view = render_result_view_selector("bottom_result_view")
if view == "標記說明":
    render_alert_summary(display_df)
    render_bottom_tag_explainer(support_months, rebound_max, rev_growth_min, price_min, int(vol_min))
elif view == "明細表":
    render_bottom_table(display_df)
    render_watchlist_adder(df_result, family_id, finmind_token)
else:
    render_data_diagnostics(data_diagnostics)
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
    st.caption("資料來源：股價來自 TWSE + TPEX OpenAPI；月營收來自 MOPS；歷史股價來自 FinMind TaiwanStockPrice。")

csv = dataframe_to_csv_bytes(display_df)
st.download_button(
    "⬇️ 下載 CSV（Excel 可直接開啟）", csv,
    f"底部剛起漲選股_{taipei_now().strftime('%Y%m%d')}.csv", "text/csv",
)

import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from data_layer.app_common import get_runtime_secret
from data_layer.data_diagnostics import (
    DataSourceDiagnostic,
    STATUS_COMPLETE,
    STATUS_FAILED,
    fetch_json_with_diagnostic,
    make_finmind_diagnostic,
)
from data_layer.export_utils import dataframe_to_csv_bytes
from data_layer.finmind_api import fetch_finmind_price_frame
from data_layer.market_api import (
    fetch_json_tpex as fetch_json_tpex_base,
    fetch_latest_twse_price_rows,
)
from data_layer.market_data import build_price_snapshot
from data_layer.mops_revenue import fetch_mops_recent_revenue_frame, latest_revenue_ym
from data_layer.portfolio_store import get_default_family_id
from data_layer.public_valuation import attach_public_valuation, fetch_public_pe_ratios_with_diagnostics
from data_layer.time_utils import taipei_now, taipei_today
from render_layer.diagnostics import render_data_diagnostics
from render_layer.style import apply_style, page_header, render_global_navigation, render_meta_strip
from render_layer.watchlist import (
    format_watchlist_number,
    render_watchlist_adder as render_watchlist_adder_base,
)


load_dotenv()


URL_TPEX_PRICE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

PRICE_MIN = 60.0
VOL_LOT_MIN = 1000
AVG_REV_YOY_MIN = 20.0
TTM_EPS_MIN = 5.0

DRAGON_PE_MAX = 30.0
DRAGON_MA60_MAX_PREMIUM = 0.30
DRAGON_MA240_MAX_PREMIUM = 0.30
HIDDEN_DRAGON_PE_MAX = 20.0
HIDDEN_DRAGON_LOW_MAX_PREMIUM = 0.20
PRICE_HISTORY_MONTHS = 12
LOW_HISTORY_MONTHS = 6
MOPS_REVENUE_CACHE_VERSION = "mops-revenue-diagnostics-v2"


st.set_page_config(page_title="雙龍吐珠", page_icon="🐉", layout="wide")
apply_style()
page_header(
    "🐉",
    "雙龍吐珠",
    "龍騰升空看季線突破，潛龍在淵看六個月低點附近的基本面轉強。",
)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_json_tpex(url: str) -> list:
    return fetch_json_tpex_base(url)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_mops_recent_revenue(latest_ym: str, months: int, cache_version: str) -> pd.DataFrame:
    _ = cache_version
    return fetch_mops_recent_revenue_frame(latest_ym, months=months)


@st.cache_data(ttl=86400, show_spinner=False)
def get_finmind_price_history(symbol: str, start_date: str, end_date: str, token: str = "") -> pd.DataFrame:
    df, status_code, msg, retry_after = fetch_finmind_price_frame(
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

    df = df.dropna(subset=["date", "low", "close"]).sort_values("date").reset_index(drop=True)
    return df[["date", "open", "high", "low", "close", "volume"]]


@st.cache_data(ttl=1800, show_spinner=False)
def get_watchlist_chart_data(symbol: str, token: str = "") -> pd.DataFrame:
    today = taipei_today()
    start_date = (today - timedelta(days=220)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")
    try:
        df, status_code, _msg, _retry_after = fetch_finmind_price_frame(
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
        df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        df["ma60"] = pd.to_numeric(df["close"], errors="coerce").rolling(60, min_periods=1).mean()
        return df.tail(120).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _roc_month_number(ym: str) -> int | None:
    clean = str(ym).strip().replace("/", "")
    if len(clean) < 5 or not clean[-2:].isdigit():
        return None
    month = int(clean[-2:])
    return month if 1 <= month <= 12 else None


def build_recent_revenue_metrics_skip_february(df_rev: pd.DataFrame, months: int = 2) -> pd.DataFrame:
    if df_rev.empty:
        return pd.DataFrame(
            columns=[
                "stock_id",
                "rev_ym",
                "rev_yoy",
                "rev_cur",
                "rev_ly",
                "avg_rev_yoy",
                "rev_months",
                "latest_rev_yoy",
                "prev_rev_yoy",
            ]
        )

    df = df_rev.copy()
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df["rev_yoy"] = pd.to_numeric(df["rev_yoy"], errors="coerce")
    df = df.dropna(subset=["stock_id", "rev_ym", "rev_yoy"])
    df = df[df["rev_ym"].map(_roc_month_number) != 2].copy()
    if df.empty:
        return pd.DataFrame()

    rows = []
    for stock_id, group in df.sort_values("rev_ym", ascending=False).groupby("stock_id"):
        selected = group.head(months).copy()
        if len(selected) < months:
            continue
        latest = selected.iloc[0]
        prev = selected.iloc[1]
        rows.append(
            {
                "stock_id": stock_id,
                "rev_ym": latest["rev_ym"],
                "rev_yoy": latest["rev_yoy"],
                "rev_cur": latest.get("rev_cur", pd.NA),
                "rev_ly": latest.get("rev_ly", pd.NA),
                "avg_rev_yoy": selected["rev_yoy"].mean(),
                "rev_months": "/".join(selected["rev_ym"].astype(str).tolist()),
                "latest_rev_yoy": latest["rev_yoy"],
                "prev_rev_yoy": prev["rev_yoy"],
            }
        )
    return pd.DataFrame(rows)


def calc_history_row(row: pd.Series, history_df: pd.DataFrame) -> dict | None:
    if history_df.empty or len(history_df) < 60:
        return None
    history_df = history_df.sort_values("date").reset_index(drop=True).copy()
    history_df["date"] = pd.to_datetime(history_df["date"], errors="coerce")
    history_df["close"] = pd.to_numeric(history_df["close"], errors="coerce")
    history_df["low"] = pd.to_numeric(history_df["low"], errors="coerce")
    history_df = history_df.dropna(subset=["date", "close", "low"])
    if len(history_df) < 60:
        return None

    latest_close = float(row["close"])
    ma60 = float(history_df["close"].tail(60).mean())
    ma240 = float(history_df["close"].tail(240).mean()) if len(history_df) >= 240 else pd.NA
    latest_date = history_df["date"].max()
    low_window_start = latest_date - timedelta(days=int(LOW_HISTORY_MONTHS * 31))
    low_df = history_df[history_df["date"] >= low_window_start]
    if low_df.empty:
        low_df = history_df
    low_idx = low_df["low"].idxmin()
    low_row = history_df.loc[low_idx]
    six_month_low = float(low_row["low"])
    return {
        "stock_id": str(row["stock_id"]),
        "ma60": ma60,
        "ma240": ma240,
        "six_month_low": six_month_low,
        "six_month_low_date": pd.to_datetime(low_row["date"]).strftime("%Y-%m-%d"),
        "ma60_premium_pct": (latest_close / ma60 - 1) * 100 if ma60 > 0 else pd.NA,
        "ma240_premium_pct": (latest_close / ma240 - 1) * 100 if pd.notna(ma240) and ma240 > 0 else pd.NA,
        "low_premium_pct": (latest_close / six_month_low - 1) * 100 if six_month_low > 0 else pd.NA,
        "history_days": len(history_df),
    }


def parse_finmind_retry_seconds(error_msg: str):
    parts = str(error_msg).split(":", 3)
    if len(parts) < 3:
        return None
    try:
        return max(int(float(parts[2])), 0)
    except Exception:
        return None


def parse_finmind_limit_status(error_msg: str):
    parts = str(error_msg).split(":", 3)
    if len(parts) < 2:
        return None
    try:
        return int(float(parts[1]))
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


def make_strategy_frames(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    dragon = df[
        df["ma60"].notna()
        & df["ma240"].notna()
        & (df["close"] > df["ma60"])
        & (df["close"] <= df["ma60"] * (1 + DRAGON_MA60_MAX_PREMIUM))
        & (df["close"] <= df["ma240"] * (1 + DRAGON_MA240_MAX_PREMIUM))
        & (df["pe_ratio"] <= DRAGON_PE_MAX)
    ].copy()
    hidden = df[
        df["six_month_low"].notna()
        & (df["close"] <= df["six_month_low"] * (1 + HIDDEN_DRAGON_LOW_MAX_PREMIUM))
        & (df["pe_ratio"] <= HIDDEN_DRAGON_PE_MAX)
    ].copy()

    dragon["strategy"] = "龍騰升空"
    hidden["strategy"] = "潛龍在淵"
    dragon = dragon.sort_values(["avg_rev_yoy", "ttm_eps"], ascending=[False, False]).reset_index(drop=True)
    hidden = hidden.sort_values(["low_premium_pct", "avg_rev_yoy"], ascending=[True, False]).reset_index(drop=True)
    return dragon, hidden


def make_combined_strategy_frame(dragon_df: pd.DataFrame, hidden_df: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([dragon_df, hidden_df], ignore_index=True)
    if combined.empty or "stock_id" not in combined.columns:
        return combined

    rows = []
    for _stock_id, group in combined.groupby("stock_id", sort=False):
        row = group.iloc[0].copy()
        strategies = set(group["strategy"].dropna().astype(str))
        if {"龍騰升空", "潛龍在淵"}.issubset(strategies):
            row["strategy"] = "雙龍合璧"
        rows.append(row)
    return pd.DataFrame(rows).reset_index(drop=True)


def make_display_df(result_df: pd.DataFrame) -> pd.DataFrame:
    if result_df.empty:
        return pd.DataFrame(
            columns=[
                "策略",
                "股票代號",
                "股票名稱",
                "市場",
                "收盤價",
                "成交量(張)",
                "近兩月平均營收年增(%)",
                "採用營收月份",
                "近四季EPS",
                "PE",
                "季線",
                "季線溢價(%)",
                "MA240",
                "MA240 premium(%)",
                "六個月最低價",
                "最低價日期",
                "低點溢價(%)",
            ]
        )

    display_df = result_df.rename(
        columns={
            "strategy": "策略",
            "stock_id": "股票代號",
            "stock_name": "股票名稱",
            "market": "市場",
            "close": "收盤價",
            "vol_lot": "成交量(張)",
            "avg_rev_yoy": "近兩月平均營收年增(%)",
            "rev_months": "採用營收月份",
            "ttm_eps": "近四季EPS",
            "pe_ratio": "PE",
            "ma240": "MA240",
            "ma240_premium_pct": "MA240 premium(%)",
            "ma60": "季線",
            "ma60_premium_pct": "季線溢價(%)",
            "six_month_low": "六個月最低價",
            "six_month_low_date": "最低價日期",
            "low_premium_pct": "低點溢價(%)",
        }
    )
    cols = [
        "策略",
        "股票代號",
        "股票名稱",
        "市場",
        "收盤價",
        "成交量(張)",
        "近兩月平均營收年增(%)",
        "採用營收月份",
        "近四季EPS",
        "PE",
        "季線",
        "季線溢價(%)",
        "MA240",
        "MA240 premium(%)",
        "六個月最低價",
        "最低價日期",
        "低點溢價(%)",
    ]
    display_df = display_df[[col for col in cols if col in display_df.columns]].copy()
    for col in ["收盤價", "近兩月平均營收年增(%)", "近四季EPS", "PE", "季線", "季線溢價(%)", "MA240", "MA240 premium(%)", "六個月最低價", "低點溢價(%)"]:
        if col in display_df.columns:
            display_df[col] = pd.to_numeric(display_df[col], errors="coerce").round(2)
    if "成交量(張)" in display_df.columns:
        display_df["成交量(張)"] = pd.to_numeric(display_df["成交量(張)"], errors="coerce").fillna(0).round(0).astype(int)
    return display_df.sort_values("收盤價", ascending=False).reset_index(drop=True)


def render_result_table(display_df: pd.DataFrame) -> None:
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "策略": st.column_config.TextColumn("策略", width=92),
            "股票代號": st.column_config.TextColumn("股票代號", width=78),
            "股票名稱": st.column_config.TextColumn("股票名稱", width=112),
            "市場": st.column_config.TextColumn("市場", width=68),
            "收盤價": st.column_config.NumberColumn("收盤價", width=82, format="%.2f"),
            "成交量(張)": st.column_config.NumberColumn("成交量(張)", width=104, format="%d"),
            "近兩月平均營收年增(%)": st.column_config.NumberColumn("近兩月平均營收年增(%)", width=164, format="%.2f"),
            "採用營收月份": st.column_config.TextColumn("採用營收月份", width=116),
            "近四季EPS": st.column_config.NumberColumn("近四季EPS", width=96, format="%.2f"),
            "PE": st.column_config.NumberColumn("PE", width=72, format="%.2f"),
            "季線": st.column_config.NumberColumn("季線", width=86, format="%.2f"),
            "季線溢價(%)": st.column_config.NumberColumn("季線溢價(%)", width=112, format="%.2f"),
            "MA240": st.column_config.NumberColumn("MA240", width=86, format="%.2f"),
            "MA240 premium(%)": st.column_config.NumberColumn("MA240 premium(%)", width=124, format="%.2f"),
            "六個月最低價": st.column_config.NumberColumn("六個月最低價", width=116, format="%.2f"),
            "最低價日期": st.column_config.TextColumn("最低價日期", width=104),
            "低點溢價(%)": st.column_config.NumberColumn("低點溢價(%)", width=112, format="%.2f"),
        },
    )


def render_download(display_df: pd.DataFrame, label: str, file_prefix: str) -> None:
    st.download_button(
        label=label,
        data=dataframe_to_csv_bytes(display_df),
        file_name=f"{file_prefix}_{taipei_now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        disabled=display_df.empty,
    )


def render_watchlist_adder(result_df: pd.DataFrame, family_id: str, finmind_token: str = "") -> None:
    if result_df.empty:
        return

    def _label(row: pd.Series) -> str:
        return (
            f"{row['stock_id']} {row['stock_name']} | {row['strategy']} | "
            f"收盤 {format_watchlist_number(row['close'])} | "
            f"營收年增 {format_watchlist_number(row['avg_rev_yoy'], '%')} | "
            f"PE {format_watchlist_number(row['pe_ratio'])}"
        )

    def _caption(selected: dict, chart_df: pd.DataFrame) -> str:
        selected_close = pd.to_numeric(selected.get("close"), errors="coerce")
        selected_ma60 = pd.to_numeric(selected.get("ma60"), errors="coerce")
        selected_ma240 = pd.to_numeric(selected.get("ma240"), errors="coerce")
        selected_low = pd.to_numeric(selected.get("six_month_low"), errors="coerce")
        return (
            f"收盤 {format_watchlist_number(selected_close)}｜"
            f"季線 {format_watchlist_number(selected_ma60)}｜"
            f"MA240 {format_watchlist_number(selected_ma240)}｜"
            f"六個月低點 {format_watchlist_number(selected_low)}"
        )

    def _support_line(selected: dict):
        return pd.to_numeric(selected.get("six_month_low"), errors="coerce")

    render_watchlist_adder_base(
        result_df,
        family_id,
        select_columns=[
            "stock_id",
            "stock_name",
            "strategy",
            "market",
            "close",
            "avg_rev_yoy",
            "pe_ratio",
            "ma60",
            "ma240",
            "six_month_low",
        ],
        numeric_columns=["close", "avg_rev_yoy", "pe_ratio", "ma60", "ma240", "six_month_low"],
        label_builder=_label,
        chart_loader=get_watchlist_chart_data,
        selectbox_key=f"double_dragon_watchlist_symbol_{result_df['strategy'].iloc[0]}",
        add_button_key=f"double_dragon_watchlist_add_{result_df['strategy'].iloc[0]}",
        finmind_token=finmind_token,
        caption_builder=_caption,
        support_line_builder=_support_line,
    )


render_meta_strip(
    [
        {"label": "共用條件", "value": "價量 + 營收 + EPS", "sub": "股價 > 60、成交量 > 1000"},
        {"label": "營收口徑", "value": "近兩個非二月月份", "sub": "遇 2 月改取更前一月"},
        {"label": "龍騰升空", "value": "季線與年線上方 30% 內", "sub": "PE <= 30"},
        {"label": "潛龍在淵", "value": "六個月低點 20% 內", "sub": "PE <= 20"},
    ]
)

with st.sidebar:
    render_global_navigation("growth_screener")
    st.markdown("---")
    st.markdown("**庫存分組設定**")
    st.text_input(
        "family_id",
        value=st.session_state.get("inventory_family_id", get_default_family_id()),
        key="inventory_family_id",
        help="觀察清單使用的 family_id。",
    )
    st.divider()
    st.header("雙龍吐珠設定")
    finmind_token = st.text_input(
        "FinMind Token（選填）",
        value=get_runtime_secret("FINMIND_TOKEN", ""),
        type="password",
        help="查詢季線與六個月低點需要 FinMind TaiwanStockPrice。",
    ).strip()
    st.markdown("**固定篩選條件**")
    st.caption(f"股價 > {PRICE_MIN:.0f}")
    st.caption(f"收盤成交量 > {VOL_LOT_MIN:,} 張")
    st.caption(f"近兩個非二月營收 YoY 平均 >= {AVG_REV_YOY_MIN:.0f}%")
    st.caption(f"近四季 EPS >= {TTM_EPS_MIN:.0f}")
    st.caption(f"龍騰升空：收盤價 > 季線、<= 季線 * {1 + DRAGON_MA60_MAX_PREMIUM:.1f}、<= 年線 * {1 + DRAGON_MA240_MAX_PREMIUM:.1f}、PE <= {DRAGON_PE_MAX:.0f}")
    st.caption(f"潛龍在淵：收盤價 <= 六個月最低點 * {1 + HIDDEN_DRAGON_LOW_MAX_PREMIUM:.1f}、PE <= {HIDDEN_DRAGON_PE_MAX:.0f}")
    run_btn = st.button("執行雙龍吐珠篩選", use_container_width=True, type="primary")
    if st.button("清除快取與結果", use_container_width=True):
        st.cache_data.clear()
        st.session_state.pop("double_dragon_result", None)
        st.success("已清除快取與上次結果。")
        st.stop()


family_id = st.session_state.get("inventory_family_id", get_default_family_id()).strip()
if not FAMILY_ID_PATTERN.fullmatch(family_id):
    st.error("family_id 格式不正確，只能使用英數字、底線或連字號，長度 1-64。")
    st.stop()


def render_saved_result(saved: dict) -> None:
    dragon_df = saved.get("dragon", pd.DataFrame())
    hidden_df = saved.get("hidden", pd.DataFrame())
    combined_df = saved.get("combined", pd.DataFrame())
    rev_ym = saved.get("rev_ym", "-")

    st.info("顯示上次篩選結果；如需更新資料，請重新執行篩選。")
    render_result_summary(dragon_df, hidden_df, rev_ym)
    render_result_tabs(dragon_df, hidden_df, combined_df)


def render_result_summary(dragon_df: pd.DataFrame, hidden_df: pd.DataFrame, rev_ym: str) -> None:
    total_unique = pd.concat([dragon_df, hidden_df], ignore_index=True)["stock_id"].nunique() if not dragon_df.empty or not hidden_df.empty else 0
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("龍騰升空", f"{len(dragon_df)} 檔")
    col2.metric("潛龍在淵", f"{len(hidden_df)} 檔")
    col3.metric("不重複股票", f"{total_unique} 檔")
    col4.metric("最新營收月份", rev_ym)


def render_result_tabs(dragon_df: pd.DataFrame, hidden_df: pd.DataFrame, combined_df: pd.DataFrame) -> None:
    tab1, tab2, tab3 = st.tabs(["龍騰升空", "潛龍在淵", "合併清單"])
    with tab1:
        display_df = make_display_df(dragon_df)
        render_result_table(display_df)
        render_download(display_df, "下載龍騰升空 CSV", "龍騰升空")
        render_watchlist_adder(dragon_df, family_id, finmind_token)
    with tab2:
        display_df = make_display_df(hidden_df)
        render_result_table(display_df)
        render_download(display_df, "下載潛龍在淵 CSV", "潛龍在淵")
        render_watchlist_adder(hidden_df, family_id, finmind_token)
    with tab3:
        display_df = make_display_df(combined_df)
        render_result_table(display_df)
        render_download(display_df, "下載雙龍吐珠合併 CSV", "雙龍吐珠")


if not run_btn:
    if "double_dragon_result" in st.session_state:
        render_saved_result(st.session_state["double_dragon_result"])
    else:
        st.info("按下側邊欄的「執行雙龍吐珠篩選」開始掃描。")
        st.markdown(
            f"""
| 條件 | 龍騰升空 | 潛龍在淵 |
|---|---:|---:|
| 股價 | > {PRICE_MIN:.0f} | > {PRICE_MIN:.0f} |
| 收盤成交量 | > {VOL_LOT_MIN:,} 張 | > {VOL_LOT_MIN:,} 張 |
| 近兩月平均營收年增 | >= {AVG_REV_YOY_MIN:.0f}%（排除 2 月） | >= {AVG_REV_YOY_MIN:.0f}%（排除 2 月） |
| 近四季 EPS | >= {TTM_EPS_MIN:.0f} | >= {TTM_EPS_MIN:.0f} |
| PE | <= {DRAGON_PE_MAX:.0f} | <= {HIDDEN_DRAGON_PE_MAX:.0f} |
| 技術位置 | 股價 > 季線，且 <= 季線 * {1 + DRAGON_MA60_MAX_PREMIUM:.1f}，且 <= 年線 * {1 + DRAGON_MA240_MAX_PREMIUM:.1f} | 股價 <= 六個月最低點 * {1 + HIDDEN_DRAGON_LOW_MAX_PREMIUM:.1f} |
"""
        )
    st.stop()


progress = st.progress(0, text="正在下載股價與營收資料...")
data_diagnostics = []

progress.progress(8, text="正在下載 TWSE 股價資料...")
raw_twse_price, diag_twse = fetch_json_with_diagnostic(fetch_latest_twse_price_rows, "", "TWSE 股價")
data_diagnostics.append(diag_twse)

progress.progress(16, text="正在下載 TPEX 股價資料...")
raw_tpex_price, diag_tpex = fetch_json_with_diagnostic(fetch_json_tpex, URL_TPEX_PRICE, "TPEX 股價")
data_diagnostics.append(diag_tpex)

latest_rev = latest_revenue_ym()
progress.progress(26, text=f"正在下載 MOPS 月營收（{latest_rev} 起近 4 個月）...")
try:
    df_rev = fetch_mops_recent_revenue(latest_rev, months=4, cache_version=MOPS_REVENUE_CACHE_VERSION)
    mops_detail = "\n".join(str(error) for error in df_rev.attrs.get("mops_errors", []))
    if df_rev.empty and not mops_detail:
        mops_detail = (
            "MOPS returned no rows and no low-level errors were captured. "
            "This can happen if Streamlit served an older cached empty result; clear cache and rerun."
        )
    data_diagnostics.append(
        DataSourceDiagnostic(
            source="MOPS 月營收",
            status=STATUS_COMPLETE if not df_rev.empty else STATUS_FAILED,
            message="抓取成功。" if not df_rev.empty else "MOPS 月營收回傳空資料。",
            detail=mops_detail,
            records=len(df_rev),
        )
    )
except Exception as exc:
    df_rev = pd.DataFrame()
    data_diagnostics.append(
        DataSourceDiagnostic(
            source="MOPS 月營收",
            status=STATUS_FAILED,
            message="抓取失敗，無法產生可信篩選結果。",
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

progress.progress(42, text="整理價量與營收資料...")
df_price = build_price_snapshot(raw_twse_price, raw_tpex_price)
df_rev_metrics = build_recent_revenue_metrics_skip_february(df_rev, months=2)
if df_rev_metrics.empty:
    st.error("近兩個非二月營收月份不足，無法計算營收年增平均。")
    st.stop()

df_merged = df_price.merge(df_rev_metrics, on="stock_id", how="inner")
df_candidates = df_merged[
    (df_merged["close"] > PRICE_MIN)
    & (df_merged["vol_lot"] > VOL_LOT_MIN)
    & (df_merged["avg_rev_yoy"] >= AVG_REV_YOY_MIN)
].copy().reset_index(drop=True)

if df_candidates.empty:
    progress.progress(100, text="篩選完成")
    st.warning("沒有股票符合共用的股價、成交量與營收條件。")
    st.stop()

progress.progress(55, text="下載官方 PE 並反推近四季 EPS...")
df_public_pe, pe_diagnostics = fetch_public_pe_ratios_with_diagnostics()
data_diagnostics.extend(pe_diagnostics)
if df_public_pe.empty:
    progress.progress(100, text="官方 PE 取得失敗")
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.error("官方 PE 資料目前抓取失敗，無法套用 PE 與 EPS 條件。")
    st.stop()

df_candidates = attach_public_valuation(df_candidates, df_public_pe)
df_common = df_candidates[
    df_candidates["pe_ratio"].notna()
    & df_candidates["ttm_eps"].notna()
    & (df_candidates["ttm_eps"] >= TTM_EPS_MIN)
    & (df_candidates["pe_ratio"] <= DRAGON_PE_MAX)
].copy().reset_index(drop=True)

if df_common.empty:
    progress.progress(100, text="篩選完成")
    st.warning("沒有股票符合共用 EPS 條件與策略所需 PE 條件。")
    st.stop()

progress.progress(68, text=f"準備查詢近 {PRICE_HISTORY_MONTHS} 個月股價歷史：{len(df_common)} 檔...")
end_date = taipei_today()
start_date = end_date - timedelta(days=int(PRICE_HISTORY_MONTHS * 31))
start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

history_rows = []
history_failed = []
rate_limit_msg = ""


def fetch_history_metrics(row_data: dict):
    sid = str(row_data["stock_id"])
    try:
        hist = get_finmind_price_history(sid, start_str, end_str, finmind_token)
        metrics = calc_history_row(pd.Series(row_data), hist)
        if metrics is None:
            return "failed", sid
        return "ok", metrics
    except RuntimeError as exc:
        err = str(exc)
        if "FINMIND_LIMIT" in err:
            return "rate_limited", err
        return "failed", sid
    except Exception:
        return "failed", sid


done_count = 0
targets = df_common.to_dict("records")
target_iter = iter(targets)
pending = {}
history_bar = st.progress(0, text=f"查詢 FinMind 歷史股價：0 / {len(targets)} 檔...")

with ThreadPoolExecutor(max_workers=3) as executor:
    for _ in range(min(3, len(targets))):
        try:
            row_data = next(target_iter)
        except StopIteration:
            break
        pending[executor.submit(fetch_history_metrics, row_data)] = str(row_data["stock_id"])

    while pending:
        done, _not_done = wait(list(pending.keys()), return_when=FIRST_COMPLETED)
        for future in done:
            sid = pending.pop(future, "")
            status, payload = future.result()
            done_count += 1

            if status == "ok":
                history_rows.append(payload)
            elif status == "rate_limited":
                rate_limit_msg = payload
            else:
                history_failed.append(payload or sid)

            history_bar.progress(
                min(done_count / len(targets), 1.0),
                text=f"查詢 FinMind 歷史股價：{done_count} / {len(targets)} 檔...",
            )

            if rate_limit_msg:
                break

            try:
                row_data = next(target_iter)
            except StopIteration:
                continue
            pending[executor.submit(fetch_history_metrics, row_data)] = str(row_data["stock_id"])

        if rate_limit_msg:
            for future in pending:
                future.cancel()
            break

if rate_limit_msg and not history_rows:
    retry_seconds = parse_finmind_retry_seconds(rate_limit_msg)
    status_code = parse_finmind_limit_status(rate_limit_msg) or 429
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 歷史股價",
            status_code,
            rate_limit_msg,
            records=0,
            retry_after=retry_seconds,
            sample_ids=history_failed[:10],
        )
    )
    progress.progress(100, text="FinMind 查詢受限")
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.error(f"FinMind 歷史股價查詢受限，請稍後再試。預估等待：{format_wait_time(retry_seconds)}。")
    st.stop()

if rate_limit_msg:
    retry_seconds = parse_finmind_retry_seconds(rate_limit_msg)
    status_code = parse_finmind_limit_status(rate_limit_msg) or 429
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 歷史股價",
            status_code,
            rate_limit_msg,
            records=len(history_rows),
            retry_after=retry_seconds,
            sample_ids=history_failed[:10],
        )
    )
    st.warning(f"FinMind 查詢途中受限，本次只完成 {len(history_rows)} / {len(targets)} 檔，結果可能不完整。")
elif history_failed:
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 歷史股價",
            None,
            "部分股票無法取得足夠歷史股價。",
            records=len(history_rows),
            sample_ids=history_failed[:10],
        )
    )
else:
    data_diagnostics.append(make_finmind_diagnostic("FinMind 歷史股價", 200, "", records=len(history_rows)))

df_history = pd.DataFrame(history_rows)
if df_history.empty:
    progress.progress(100, text="篩選完成")
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.warning("歷史股價資料不足，無法計算季線或六個月最低點。")
    st.stop()

df_ready = df_common.merge(df_history, on="stock_id", how="inner")
dragon_df, hidden_df = make_strategy_frames(df_ready)
combined_df = make_combined_strategy_frame(dragon_df, hidden_df)

progress.progress(100, text="雙龍吐珠篩選完成")

latest_used_rev = "-"
if not df_rev_metrics.empty and "rev_ym" in df_rev_metrics.columns:
    latest_used_rev = str(df_rev_metrics["rev_ym"].mode().iloc[0])

st.session_state["double_dragon_result"] = {
    "dragon": dragon_df,
    "hidden": hidden_df,
    "combined": combined_df,
    "rev_ym": latest_used_rev,
}

st.subheader("雙龍吐珠篩選結果")
render_result_summary(dragon_df, hidden_df, latest_used_rev)
if dragon_df.empty and hidden_df.empty:
    st.warning("共用條件通過後，沒有股票符合龍騰升空或潛龍在淵的策略條件。")
    with st.expander("查看通過共用條件但未入選的股票", expanded=False):
        preview = make_display_df(df_ready.assign(strategy="共用條件通過"))
        render_result_table(preview)
else:
    render_result_tabs(dragon_df, hidden_df, combined_df)

with st.expander("資料來源與執行診斷", expanded=False):
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.caption(
        "股價與成交量來自 TWSE/TPEX OpenAPI；月營收來自 MOPS；PE 來自官方上市櫃資料；"
        "季線與六個月最低點來自 FinMind TaiwanStockPrice。"
    )

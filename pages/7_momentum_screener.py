from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import timedelta
import re

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
from data_layer.historical_price_service import clean_price_history, fetch_cached_finmind_price_history
from data_layer.market_api import (
    fetch_latest_twse_price_rows,
)
from data_layer.market_data import build_latest_revenue_view, build_price_snapshot
from data_layer.mops_revenue import latest_revenue_ym
from data_layer.portfolio_store import get_default_family_id
from data_layer.public_valuation import attach_public_valuation, fetch_public_pe_ratios_with_diagnostics
from data_layer.screener_data import (
    URL_TPEX_PRICE,
    fetch_screener_mops_revenue as fetch_mops_recent_revenue,
    fetch_screener_price_history as get_finmind_price_history,
    fetch_tpex_price_rows as fetch_json_tpex,
    parse_finmind_limit,
)
from data_layer.time_utils import taipei_now, taipei_today
from render_layer.diagnostics import render_data_diagnostics
from render_layer.style import apply_style, page_header, render_global_navigation, render_meta_strip
from render_layer.watchlist import (
    format_watchlist_number,
    render_watchlist_adder as render_watchlist_adder_base,
)


load_dotenv()


PRICE_MIN = 20.0
PRICE_MAX = 50.0
REV_YOY_MIN = 30.0
VOL_LOT_MIN = 300.0
TTM_EPS_MIN = 1.0
MA240_MAX_PREMIUM = 0.20
PRICE_HISTORY_DAYS = 420
MA240_DAYS = 240
FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


st.set_page_config(page_title="小型飆股起漲策略", page_icon="S", layout="wide")
apply_style()
page_header(
    "S",
    "小型飆股起漲策略",
    "用低中價位、單月營收高成長與年線乖離控制，尋找剛要發動的小型股候選名單。",
)


@st.cache_data(ttl=1800, show_spinner=False)
def get_momentum_watchlist_chart_data(symbol: str, token: str = "") -> pd.DataFrame:
    today = taipei_today()
    start_date = (today - timedelta(days=430)).strftime("%Y-%m-%d")
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
        close = pd.to_numeric(df["close"], errors="coerce")
        df["ma60"] = close.rolling(60, min_periods=1).mean()
        df["ma240"] = close.rolling(MA240_DAYS, min_periods=MA240_DAYS).mean()
        return df.tail(180).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def calc_ma240_row(row: pd.Series, history_df: pd.DataFrame) -> dict | None:
    if history_df.empty or len(history_df) < MA240_DAYS:
        return None

    hist = history_df.sort_values("date").reset_index(drop=True).copy()
    hist["date"] = pd.to_datetime(hist["date"], errors="coerce")
    hist["close"] = pd.to_numeric(hist["close"], errors="coerce")
    hist = hist.dropna(subset=["date", "close"])
    if len(hist) < MA240_DAYS:
        return None

    latest_close = float(pd.to_numeric(row["close"], errors="coerce"))
    ma240 = float(hist["close"].tail(MA240_DAYS).mean())
    if ma240 <= 0:
        return None

    latest_hist_close = float(hist["close"].iloc[-1])
    latest_hist_date = pd.to_datetime(hist["date"].iloc[-1]).strftime("%Y-%m-%d")
    ma240_premium_pct = (latest_close / ma240 - 1) * 100

    return {
        "stock_id": str(row["stock_id"]),
        "stock_name": str(row["stock_name"]),
        "market": str(row["market"]),
        "close": latest_close,
        "vol_lot": float(pd.to_numeric(row["vol_lot"], errors="coerce")),
        "rev_ym": str(row["rev_ym"]),
        "rev_yoy": float(pd.to_numeric(row["rev_yoy"], errors="coerce")),
        "ttm_eps": pd.to_numeric(row.get("ttm_eps"), errors="coerce"),
        "pe_ratio": pd.to_numeric(row.get("pe_ratio"), errors="coerce"),
        "rev_cur": pd.to_numeric(row.get("rev_cur"), errors="coerce"),
        "rev_ly": pd.to_numeric(row.get("rev_ly"), errors="coerce"),
        "ma240": ma240,
        "ma240_limit": ma240 * (1 + MA240_MAX_PREMIUM),
        "ma240_premium_pct": ma240_premium_pct,
        "latest_hist_close": latest_hist_close,
        "latest_hist_date": latest_hist_date,
        "history_days": len(hist),
    }


def make_display_df(result_df: pd.DataFrame) -> pd.DataFrame:
    if result_df.empty:
        return pd.DataFrame(
            columns=[
                "股票代號",
                "股票名稱",
                "市場",
                "收盤價",
                "成交量(張)",
                "月營收年增率(%)",
                "近四季EPS",
                "PE",
                "營收年月",
                "年線",
                "年線1.2倍",
                "年線乖離(%)",
                "歷史價日期",
                "歷史交易日數",
            ]
        )

    display_df = result_df.rename(
        columns={
            "stock_id": "股票代號",
            "stock_name": "股票名稱",
            "market": "市場",
            "close": "收盤價",
            "vol_lot": "成交量(張)",
            "rev_yoy": "月營收年增率(%)",
            "ttm_eps": "近四季EPS",
            "pe_ratio": "PE",
            "rev_ym": "營收年月",
            "ma240": "年線",
            "ma240_limit": "年線1.2倍",
            "ma240_premium_pct": "年線乖離(%)",
            "latest_hist_date": "歷史價日期",
            "history_days": "歷史交易日數",
        }
    )
    columns = [
        "股票代號",
        "股票名稱",
        "市場",
        "收盤價",
        "成交量(張)",
        "月營收年增率(%)",
        "近四季EPS",
        "PE",
        "營收年月",
        "年線",
        "年線1.2倍",
        "年線乖離(%)",
        "歷史價日期",
        "歷史交易日數",
    ]
    display_df = display_df[[col for col in columns if col in display_df.columns]].copy()
    for col in ["收盤價", "月營收年增率(%)", "近四季EPS", "PE", "年線", "年線1.2倍", "年線乖離(%)"]:
        if col in display_df.columns:
            display_df[col] = pd.to_numeric(display_df[col], errors="coerce").round(2)
    display_df["成交量(張)"] = pd.to_numeric(display_df["成交量(張)"], errors="coerce").fillna(0).round(0).astype(int)
    display_df["歷史交易日數"] = pd.to_numeric(display_df["歷史交易日數"], errors="coerce").fillna(0).round(0).astype(int)
    return display_df.sort_values(["收盤價", "月營收年增率(%)"], ascending=[False, False]).reset_index(drop=True)


def render_result_table(display_df: pd.DataFrame) -> None:
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "股票代號": st.column_config.TextColumn("股票代號", width=78),
            "股票名稱": st.column_config.TextColumn("股票名稱", width=112),
            "市場": st.column_config.TextColumn("市場", width=64),
            "收盤價": st.column_config.NumberColumn("收盤價", width=84, format="%.2f"),
            "成交量(張)": st.column_config.NumberColumn("成交量(張)", width=108, format="%d"),
            "月營收年增率(%)": st.column_config.NumberColumn("月營收年增率(%)", width=138, format="%.2f"),
            "近四季EPS": st.column_config.NumberColumn("近四季EPS", width=96, format="%.2f"),
            "PE": st.column_config.NumberColumn("PE", width=72, format="%.2f"),
            "營收年月": st.column_config.TextColumn("營收年月", width=92),
            "年線": st.column_config.NumberColumn("年線", width=84, format="%.2f"),
            "年線1.2倍": st.column_config.NumberColumn("年線1.2倍", width=96, format="%.2f"),
            "年線乖離(%)": st.column_config.NumberColumn("年線乖離(%)", width=110, format="%.2f"),
            "歷史價日期": st.column_config.TextColumn("歷史價日期", width=106),
            "歷史交易日數": st.column_config.NumberColumn("歷史交易日數", width=112, format="%d"),
        },
    )


def render_summary(result_df: pd.DataFrame, stage_counts: dict, rev_ym: str) -> None:
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("符合標的", f"{len(result_df)} 檔")
    col2.metric("價格與營收候選", f"{stage_counts.get('price_revenue', 0)} 檔")
    col3.metric("成交量候選", f"{stage_counts.get('volume', 0)} 檔")
    col4.metric("EPS候選", f"{stage_counts.get('eps', 0)} 檔")
    col5.metric("年線可判讀", f"{stage_counts.get('ma240_ready', 0)} 檔")
    col6.metric("最新營收年月", rev_ym)


def render_download(display_df: pd.DataFrame) -> None:
    st.download_button(
        "下載篩選結果 CSV",
        data=dataframe_to_csv_bytes(display_df),
        file_name=f"小型飆股起漲策略_{taipei_now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        disabled=display_df.empty,
    )


def render_watchlist_adder(result_df: pd.DataFrame, family_id: str, finmind_token: str = "") -> None:
    if result_df.empty:
        return

    def _label(row: dict) -> str:
        return (
            f"{row['stock_id']} {row['stock_name']} | {row['market']} | "
            f"close {format_watchlist_number(row['close'])} | "
            f"revenue YoY {format_watchlist_number(row['rev_yoy'], '%')} | "
            f"EPS {format_watchlist_number(row['ttm_eps'])} | "
            f"MA240 {format_watchlist_number(row['ma240'])}"
        )

    def _caption(selected: dict, chart_df: pd.DataFrame) -> str:
        selected_close = pd.to_numeric(selected.get("close"), errors="coerce")
        selected_eps = pd.to_numeric(selected.get("ttm_eps"), errors="coerce")
        selected_ma240 = pd.to_numeric(selected.get("ma240"), errors="coerce")
        selected_premium = pd.to_numeric(selected.get("ma240_premium_pct"), errors="coerce")
        latest_chart_ma240 = None
        if not chart_df.empty and "ma240" in chart_df.columns and chart_df["ma240"].notna().any():
            latest_chart_ma240 = pd.to_numeric(chart_df["ma240"].dropna().iloc[-1], errors="coerce")
        ma240_value = selected_ma240 if pd.notna(selected_ma240) else latest_chart_ma240
        return (
            f"close {format_watchlist_number(selected_close)} | "
            f"EPS {format_watchlist_number(selected_eps)} | "
            f"MA240 {format_watchlist_number(ma240_value)} | "
            f"MA240 premium {format_watchlist_number(selected_premium, '%')}"
        )

    render_watchlist_adder_base(
        result_df,
        family_id,
        select_columns=[
            "stock_id",
            "stock_name",
            "market",
            "close",
            "vol_lot",
            "rev_yoy",
            "ttm_eps",
            "pe_ratio",
            "ma240",
            "ma240_limit",
            "ma240_premium_pct",
        ],
        numeric_columns=["close", "vol_lot", "rev_yoy", "ttm_eps", "pe_ratio", "ma240", "ma240_limit", "ma240_premium_pct"],
        label_builder=_label,
        chart_loader=get_momentum_watchlist_chart_data,
        selectbox_key="momentum_watchlist_symbol",
        add_button_key="momentum_watchlist_add",
        finmind_token=finmind_token,
        caption_builder=_caption,
    )


def render_saved_result(saved: dict) -> None:
    result_df = saved.get("result", pd.DataFrame())
    stage_counts = saved.get("stage_counts", {})
    rev_ym = saved.get("rev_ym", "-")
    st.info("顯示上一次篩選結果；如需更新資料，請重新執行篩選。")
    render_summary(result_df, stage_counts, rev_ym)
    display_df = make_display_df(result_df)
    render_result_table(display_df)
    render_download(display_df)
    render_watchlist_adder(result_df, family_id, finmind_token)


render_meta_strip(
    [
        {"label": "價格區間", "value": "20 到 50 元", "sub": "使用 TWSE/TPEX 最新收盤價"},
        {"label": "營收動能", "value": "YoY > 30%", "sub": "使用 MOPS 最新完整月份"},
        {"label": "流動性", "value": "成交量 > 300張", "sub": "TWSE/TPEX 最新價量"},
        {"label": "獲利門檻", "value": "近四季EPS > 1", "sub": "官方 PE 反推"},
        {"label": "年線位置", "value": "<= 年線 1.2 倍", "sub": "FinMind 近一年歷史價格"},
    ]
)

with st.sidebar:
    render_global_navigation("momentum_screener")
    st.markdown("---")
    st.header("策略參數")
    st.markdown("**自選股清單**")
    st.text_input(
        "family_id",
        value=st.session_state.get("inventory_family_id", get_default_family_id()),
        key="inventory_family_id",
        help="用來和庫存總覽、自選股頁共用同一份清單。",
    )
    st.divider()
    finmind_token = st.text_input(
        "FinMind Token（選填）",
        value=get_runtime_secret("FINMIND_TOKEN", ""),
        type="password",
        help="年線需要 FinMind TaiwanStockPrice；若無 Token 仍可嘗試，但較容易遇到限制。",
    ).strip()
    max_history_targets = int(
        st.number_input(
            "年線檢查上限（0 代表全部）",
            value=0,
            min_value=0,
            step=10,
            help="候選股很多時可先限制檢查檔數；0 會檢查全部價格與營收候選。",
        )
    )
    run_btn = st.button("執行篩選", use_container_width=True, type="primary")
    if st.button("清除快取與結果", use_container_width=True):
        st.cache_data.clear()
        st.session_state.pop("momentum_screener_result", None)
        st.success("已清除快取與本頁結果。")
        st.stop()

    st.markdown("---")
    st.caption("資料來源：股價 TWSE/TPEX OpenAPI；月營收 MOPS；年線 FinMind TaiwanStockPrice。")


family_id = st.session_state.get("inventory_family_id", get_default_family_id()).strip()
if not FAMILY_ID_PATTERN.fullmatch(family_id):
    st.error("family_id 只能使用英數字、底線或連字號，長度需在 1 到 64 字元內。")
    st.stop()


if not run_btn:
    if "momentum_screener_result" in st.session_state:
        render_saved_result(st.session_state["momentum_screener_result"])
    else:
        st.info("設定完成後按下「執行篩選」，系統會先用官方資料縮小候選名單，再用三線程計算年線。")
        st.markdown(
            f"""
| 條件 | 門檻 | 資料來源 |
|---|---:|---|
| 股價 | {PRICE_MIN:.0f} <= 收盤價 <= {PRICE_MAX:.0f} | TWSE/TPEX OpenAPI |
| 月營收年增率 | > {REV_YOY_MIN:.0f}% | MOPS 最新完整月份 |
| 成交量 | > {VOL_LOT_MIN:.0f} 張 | TWSE/TPEX OpenAPI |
| 近四季 EPS | > {TTM_EPS_MIN:.0f} | 官方 PE 反推 |
| 年線位置 | 收盤價 <= 年線 * {1 + MA240_MAX_PREMIUM:.1f} | FinMind TaiwanStockPrice |
"""
        )
    st.stop()


progress = st.progress(0, text="抓取 TWSE/TPEX 最新股價...")
data_diagnostics: list[DataSourceDiagnostic] = []
stage_counts: dict[str, int] = {}

raw_twse_price, diag_twse = fetch_json_with_diagnostic(fetch_latest_twse_price_rows, "", "TWSE 股價")
data_diagnostics.append(diag_twse)

progress.progress(12, text="抓取 TPEX 最新股價...")
raw_tpex_price, diag_tpex = fetch_json_with_diagnostic(fetch_json_tpex, URL_TPEX_PRICE, "TPEX 股價")
data_diagnostics.append(diag_tpex)

latest_rev = latest_revenue_ym()
progress.progress(24, text=f"抓取 MOPS 月營收（{latest_rev}）...")
try:
    df_rev = fetch_mops_recent_revenue(latest_rev, months=1)
    mops_detail = "\n".join(str(error) for error in df_rev.attrs.get("mops_errors", []))
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

render_data_diagnostics(data_diagnostics, expanded=any(item.status != STATUS_COMPLETE for item in data_diagnostics))

if not raw_twse_price and not raw_tpex_price:
    st.error("TWSE/TPEX 股價資料無法取得，本頁無法產生可信篩選結果。")
    st.stop()
if df_rev.empty:
    st.error("MOPS 月營收資料無法取得，本頁無法產生可信篩選結果。")
    st.stop()

progress.progress(38, text="整理價格與營收條件...")
df_price = build_price_snapshot(raw_twse_price, raw_tpex_price)
df_rev_latest = build_latest_revenue_view(df_rev)
stage_counts["price_rows"] = len(df_price)
stage_counts["revenue_rows"] = len(df_rev_latest)

df_price_filtered = df_price[
    (pd.to_numeric(df_price["close"], errors="coerce") >= PRICE_MIN)
    & (pd.to_numeric(df_price["close"], errors="coerce") <= PRICE_MAX)
].copy()
stage_counts["price"] = len(df_price_filtered)

df_merged = df_price_filtered.merge(
    df_rev_latest[["stock_id", "rev_ym", "rev_yoy", "rev_cur", "rev_ly"]],
    on="stock_id",
    how="inner",
)
df_candidates = df_merged[
    pd.to_numeric(df_merged["rev_yoy"], errors="coerce") > REV_YOY_MIN
].copy().reset_index(drop=True)
stage_counts["price_revenue"] = len(df_candidates)

if df_candidates.empty:
    progress.progress(100, text="篩選完成")
    render_summary(pd.DataFrame(), stage_counts, latest_rev)
    st.warning("沒有股票同時符合股價區間與月營收年增條件。")
    st.stop()

progress.progress(46, text="套用成交量條件...")
df_candidates = df_candidates[
    pd.to_numeric(df_candidates["vol_lot"], errors="coerce") > VOL_LOT_MIN
].copy().reset_index(drop=True)
stage_counts["volume"] = len(df_candidates)

if df_candidates.empty:
    progress.progress(100, text="篩選完成")
    render_summary(pd.DataFrame(), stage_counts, latest_rev)
    st.warning("沒有股票同時符合價格、營收與成交量條件。")
    st.stop()

progress.progress(50, text="下載官方 PE 並反推近四季 EPS...")
df_public_pe, pe_diagnostics = fetch_public_pe_ratios_with_diagnostics()
data_diagnostics.extend(pe_diagnostics)
if df_public_pe.empty:
    progress.progress(100, text="官方 PE 取得失敗")
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.error("官方 PE 資料目前抓取失敗，無法套用近四季 EPS 條件。")
    st.stop()

df_candidates = attach_public_valuation(df_candidates, df_public_pe)
df_candidates = df_candidates[
    df_candidates["ttm_eps"].notna()
    & (pd.to_numeric(df_candidates["ttm_eps"], errors="coerce") > TTM_EPS_MIN)
].copy().reset_index(drop=True)
stage_counts["eps"] = len(df_candidates)

if df_candidates.empty:
    progress.progress(100, text="篩選完成")
    render_summary(pd.DataFrame(), stage_counts, latest_rev)
    st.warning("沒有股票同時符合價格、營收、成交量與近四季 EPS 條件。")
    st.stop()

df_targets = df_candidates.sort_values(["rev_yoy", "ttm_eps", "vol_lot"], ascending=[False, False, False]).reset_index(drop=True)
if max_history_targets > 0:
    df_targets = df_targets.head(max_history_targets).copy()

end_date = taipei_today()
start_date = end_date - timedelta(days=PRICE_HISTORY_DAYS)
start_str = start_date.strftime("%Y-%m-%d")
end_str = end_date.strftime("%Y-%m-%d")

progress.progress(56, text=f"三線程計算年線：0 / {len(df_targets)}")
history_rows = []
history_failed = []
rate_limit_msg = ""

history_bar = st.progress(0, text=f"FinMind 年線檢查：0 / {len(df_targets)}")


def fetch_ma240_result(row_data: dict):
    sid = str(row_data["stock_id"])
    try:
        hist = get_finmind_price_history(sid, start_str, end_str, finmind_token)
        metrics = calc_ma240_row(pd.Series(row_data), hist)
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


targets = df_targets.to_dict("records")
done_count = 0
target_iter = iter(targets)
pending = {}

with ThreadPoolExecutor(max_workers=3) as executor:
    for _ in range(min(3, len(targets))):
        row_data = next(target_iter, None)
        if row_data is None:
            break
        pending[executor.submit(fetch_ma240_result, row_data)] = str(row_data["stock_id"])

    while pending:
        done, _not_done = wait(list(pending.keys()), return_when=FIRST_COMPLETED)
        for future in done:
            sid = pending.pop(future, "")
            status, payload = future.result()
            done_count += 1

            if status == "ok":
                history_rows.append(payload)
            elif status == "rate_limited":
                rate_limit_msg = str(payload)
            else:
                history_failed.append(payload or sid)

            ratio = min(done_count / len(targets), 1.0)
            history_bar.progress(ratio, text=f"FinMind 年線檢查：{done_count} / {len(targets)}")

            if rate_limit_msg:
                break

            row_data = next(target_iter, None)
            if row_data is not None:
                pending[executor.submit(fetch_ma240_result, row_data)] = str(row_data["stock_id"])

        if rate_limit_msg:
            for future in pending:
                future.cancel()
            break

if rate_limit_msg:
    status_code, retry_after = parse_finmind_limit(rate_limit_msg)
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 年線",
            status_code or 429,
            rate_limit_msg,
            records=len(history_rows),
            retry_after=retry_after,
            sample_ids=history_failed[:10],
        )
    )
    render_data_diagnostics(data_diagnostics, expanded=True)
    if not history_rows:
        st.error("FinMind 查詢受限，年線資料未完成。本次結果不完整，請稍後重跑或提供 Token。")
        st.stop()
    st.warning(f"FinMind 查詢中途受限，只完成 {len(history_rows)} / {len(df_targets)} 檔年線檢查。")
elif history_failed:
    data_diagnostics.append(
        make_finmind_diagnostic(
            "FinMind 年線",
            None,
            "部分股票無法取得足夠歷史價格計算年線。",
            records=len(history_rows),
            sample_ids=history_failed[:10],
        )
    )
else:
    data_diagnostics.append(make_finmind_diagnostic("FinMind 年線", 200, "", records=len(history_rows)))

df_history = pd.DataFrame(history_rows)
stage_counts["ma240_ready"] = len(df_history)

if df_history.empty:
    progress.progress(100, text="篩選完成")
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.warning("已通過價格與營收條件的股票，沒有足夠歷史價格可計算年線。")
    st.stop()

df_result = df_history[
    pd.to_numeric(df_history["close"], errors="coerce")
    <= pd.to_numeric(df_history["ma240_limit"], errors="coerce")
].copy().reset_index(drop=True)
df_result = df_result.sort_values(["close", "rev_yoy"], ascending=[False, False]).reset_index(drop=True)
stage_counts["result"] = len(df_result)

progress.progress(100, text="篩選完成")

st.session_state["momentum_screener_result"] = {
    "result": df_result,
    "stage_counts": stage_counts,
    "rev_ym": latest_rev,
}

st.subheader("篩選結果")
render_summary(df_result, stage_counts, latest_rev)

display_df = make_display_df(df_result)
if df_result.empty:
    st.warning("有候選股完成年線計算，但沒有股票符合收盤價 <= 年線 * 1.2。")
    with st.expander("查看年線已完成但未通過的候選股", expanded=False):
        preview = make_display_df(df_history)
        render_result_table(preview)
else:
    render_result_table(display_df)
    render_download(display_df)
    render_watchlist_adder(df_result, family_id, finmind_token)

with st.expander("資料與篩選診斷", expanded=False):
    render_data_diagnostics(data_diagnostics, expanded=True)
    st.write(
        {
            "price_rows": stage_counts.get("price_rows", 0),
            "price_20_to_50": stage_counts.get("price", 0),
            "price_revenue_candidates": stage_counts.get("price_revenue", 0),
            "volume_candidates": stage_counts.get("volume", 0),
            "eps_candidates": stage_counts.get("eps", 0),
            "ma240_ready": stage_counts.get("ma240_ready", 0),
            "result": stage_counts.get("result", 0),
            "history_window": f"{start_str} ~ {end_str}",
        }
    )

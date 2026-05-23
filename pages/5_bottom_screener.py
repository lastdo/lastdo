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
from _market_api import fetch_json_tpex as fetch_json_tpex_base, fetch_json_twse as fetch_json_twse_base

load_dotenv()

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

# ─────────────────────────────────────────────
# 側邊欄
# ─────────────────────────────────────────────
with st.sidebar:
    render_global_navigation("bottom_screener")
    st.markdown("---")
    st.header("⚙️ 選股條件")
    st.divider()

    finmind_token = st.text_input(
        "FinMind Token（選填）",
        value=os.getenv("FINMIND_TOKEN", ""),
        type="password",
        help="用於查詢通過前置條件股票的近半年歷史股價及去年全年EPS；未輸入時略過EPS篩選。",
    ).strip()

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
    last_yr_eps_min = st.number_input(
        "去年全年EPS 大於（元）", value=5.0, min_value=0.0, max_value=500.0, step=0.5,
        help="去年（上一個完整會計年度）四季EPS合計，需 FinMind Token；未輸入 Token 時略過。",
    )

    run_btn = st.button("🔍 開始選股", use_container_width=True, type="primary")
    if st.button("🗑️ 清除快取（強制重新抓資料）", use_container_width=True):
        st.session_state.pop("bottom_screener_result", None)
        st.success("✅ 本頁結果已清除，請重新選股")
        st.stop()

    st.markdown("---")
    st.caption("📡 股價/月營收：TWSE + TPEX OpenAPI（免費）")
    st.caption("📡 近半年歷史股價：FinMind TaiwanStockPrice（三線程查詢）")
    st.caption("📡 去年全年EPS：FinMind TaiwanStockFinancialStatements（三線程查詢）")
    st.caption("📢 本系統僅供學術研究，不構成投資建議")


def clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("--", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


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
    _has_eps = "last_yr_eps" in result_df.columns
    _rename = {
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
        "股票代碼", "股票名稱", "市場", "收盤價(元)", "近半年支撐價(元)", "支撐日期",
        "自底部漲幅(%)", "前一日成交量(張)", "單月營收年增率(%)", "最新營收年月", "歷史交易日數",
    ]
    if _has_eps:
        _rename["last_yr_eps"] = "去年全年EPS(元)"
        _cols.insert(_cols.index("歷史交易日數"), "去年全年EPS(元)")
    display_df = result_df.rename(columns=_rename)[_cols]
    for col in ["收盤價(元)", "近半年支撐價(元)", "自底部漲幅(%)", "單月營收年增率(%)"]:
        display_df[col] = pd.to_numeric(display_df[col], errors="coerce").round(2)
    display_df["前一日成交量(張)"] = pd.to_numeric(
        display_df["前一日成交量(張)"], errors="coerce"
    ).fillna(0).round(0).astype(int)
    display_df["歷史交易日數"] = pd.to_numeric(
        display_df["歷史交易日數"], errors="coerce"
    ).fillna(0).round(0).astype(int)
    if _has_eps:
        display_df["去年全年EPS(元)"] = pd.to_numeric(
            display_df["去年全年EPS(元)"], errors="coerce"
        ).round(2)
    return display_df.sort_values(
        ["自底部漲幅(%)", "單月營收年增率(%)"], ascending=[True, False]
    ).reset_index(drop=True)


if not run_btn:
    if "bottom_screener_result" in st.session_state:
        _r = st.session_state["bottom_screener_result"]
        st.info("💡 顯示上次選股結果。如需重新選股請點擊「開始選股」。")
        _disp = make_display_df(_r)
        st.subheader(f"📋 底部剛起漲名單（共 {len(_disp)} 檔）")
        st.dataframe(_disp, use_container_width=True, hide_index=True)
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
| 去年全年EPS | > **{last_yr_eps_min:.1f}** 元 | FinMind TaiwanStockFinancialStatements |
| 本益比 | **不篩選** | 已移除 |

**策略邏輯：**

先剔除 100 元以下股票，再用成交量與月營收年增率篩出基本流動性與營收仍正向的股票，
再查詢候選股近 {support_months} 個月歷史價格，以期間最低價作為底部支撐價，
通過起漲幅條件後再以去年全年EPS篩選，確保基本盈利能力仍佳。

> 通過股價、成交量與營收條件的候選股會全部進入近半年支撐價及EPS篩選。
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
    low_idx = history_df["low"].idxmin()
    support_price = float(history_df.loc[low_idx, "low"])
    if support_price <= 0:
        return None
    latest_close = float(row["close"])
    rebound_pct = (latest_close / support_price - 1) * 100
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
        "support_date": history_df.loc[low_idx, "date"].strftime("%Y-%m-%d"),
        "rebound_pct": rebound_pct,
        "history_days": len(history_df),
    }


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
df_twse_p = pd.DataFrame(raw_twse_price)[["Code", "Name", "ClosingPrice", "TradeVolume"]].copy()
df_twse_p = df_twse_p.rename(columns={
    "Code": "stock_id", "Name": "stock_name",
    "ClosingPrice": "close", "TradeVolume": "vol_shares",
})
df_twse_p["market"] = "上市"

df_tpex_p = pd.DataFrame(raw_tpex_price)[[
    "SecuritiesCompanyCode", "CompanyName", "Close", "TradingShares",
]].copy()
df_tpex_p = df_tpex_p.rename(columns={
    "SecuritiesCompanyCode": "stock_id", "CompanyName": "stock_name",
    "Close": "close", "TradingShares": "vol_shares",
})
df_tpex_p["market"] = "上櫃"

df_price = pd.concat([df_twse_p, df_tpex_p], ignore_index=True)
df_price["close"] = clean_numeric(df_price["close"])
df_price["vol_shares"] = clean_numeric(df_price["vol_shares"])
df_price["vol_lot"] = df_price["vol_shares"] / 1000
df_price["stock_id"] = df_price["stock_id"].astype(str).str.strip()
df_price = df_price[["stock_id", "stock_name", "market", "close", "vol_lot"]].dropna()

df_price_filtered = df_price[
    (df_price["close"] > price_min) & (df_price["vol_lot"] >= vol_min)
].copy().reset_index(drop=True)

# ─────────────────────────────────────────────
# Step 3：整理最新單月營收
# ─────────────────────────────────────────────
rev_col_map = {
    "公司代號": "stock_id",
    "資料年月": "rev_ym",
    "營業收入-當月營收": "rev_cur",
    "營業收入-去年當月營收": "rev_ly",
    "營業收入-去年同月增減(%)": "rev_yoy",
}
df_twse_r = pd.DataFrame(raw_twse_rev).rename(columns=rev_col_map)[list(rev_col_map.values())].copy()
df_tpex_r = pd.DataFrame(raw_tpex_rev).rename(columns=rev_col_map)[list(rev_col_map.values())].copy()

df_rev = pd.concat([df_twse_r, df_tpex_r], ignore_index=True)
df_rev["rev_yoy"] = clean_numeric(df_rev["rev_yoy"])
df_rev["rev_cur"] = clean_numeric(df_rev["rev_cur"])
df_rev["rev_ly"] = clean_numeric(df_rev["rev_ly"])
df_rev["stock_id"] = df_rev["stock_id"].astype(str).str.strip()
df_rev = df_rev.dropna(subset=["rev_yoy"])

df_rev_latest = (
    df_rev.sort_values(["stock_id", "rev_ym"], ascending=[True, False])
    .groupby("stock_id", as_index=False)
    .first()
)

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
    f"通過股價、成交量與營收條件的 {len(df_history_targets)} 檔，將全部查詢近半年歷史股價。"
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
# Step 6：三線程查詢去年EPS，篩選 EPS > last_yr_eps_min
# ─────────────────────────────────────────────
if df_result.empty:
    pass  # 無候選股，跳過 EPS 查詢
elif not finmind_token:
    st.info("ℹ️ 未輸入 FinMind Token，略過去年EPS篩選。")
else:
    _eps_n = len(df_result)
    eps_bar = st.progress(0, text=f"📊 三線程查詢去年EPS（0 / {_eps_n} 檔）...")
    _eps_results: dict = {}
    _eps_banned_msg = ""
    _eps_done = 0

    def fetch_eps_row(sid: str):
        try:
            val = get_finmind_last_yr_eps(sid, finmind_token)
            return "ok", sid, val
        except RuntimeError as _e:
            _err = str(_e)
            if "FINMIND_BANNED" in _err:
                return "banned", sid, _err
            return "failed", sid, None
        except Exception:
            return "failed", sid, None

    with ThreadPoolExecutor(max_workers=3) as _eps_executor:
        _eps_futures_list = [
            _eps_executor.submit(fetch_eps_row, str(r["stock_id"]))
            for _, r in df_result.iterrows()
        ]
        for _f in as_completed(_eps_futures_list):
            _sts, _sid, _payload = _f.result()
            _eps_done += 1
            if _sts == "ok":
                _eps_results[_sid] = _payload
            elif _sts == "banned":
                _eps_banned_msg = _payload
                for _pf in _eps_futures_list:
                    _pf.cancel()
                break
            else:
                _eps_results[_sid] = None
            eps_bar.progress(
                min(_eps_done / _eps_n, 1.0),
                text=f"📊 三線程查詢去年EPS（{_eps_done} / {_eps_n} 檔）...",
            )

    eps_bar.progress(1.0, text="✅ 去年EPS查詢完成")

    if _eps_banned_msg and not _eps_results:
        _r2 = parse_finmind_retry_seconds(_eps_banned_msg)
        st.error(
            f"❌ FinMind API 查詢 EPS 時 IP 暫時封鎖。\n\n"
            f"剩餘等待時間：約 **{format_wait_time(_r2)}**；"
            f"預估可重新查詢時間：**{format_retry_at(_r2)}**。"
        )
        st.stop()

    if _eps_banned_msg and _eps_results:
        _r2 = parse_finmind_retry_seconds(_eps_banned_msg)
        st.warning(
            f"⚠️ FinMind EPS 查詢中途被 rate limit，僅完成 {len(_eps_results)} / {_eps_n} 檔，結果可能不完整。"
            f"剩餘等待時間：約 **{format_wait_time(_r2)}**；預估可重新查詢時間：**{format_retry_at(_r2)}**。"
        )

    df_result["last_yr_eps"] = df_result["stock_id"].astype(str).map(_eps_results)
    df_result = df_result[
        df_result["last_yr_eps"].notna() & (df_result["last_yr_eps"] > last_yr_eps_min)
    ].copy().reset_index(drop=True)

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
col5.metric("去年EPS", f"> {last_yr_eps_min:.1f} 元" if finmind_token else "（未查詢）")

st.divider()

with st.expander("🔎 篩選流程診斷", expanded=False):
    st.write(
        f"成交量+營收通過：{n_candidates} 檔｜"
        f"歷史股價查詢：{n_targets} 檔｜"
        f"可計算支撐價：{len(df_support)} 檔｜"
        f"歷史資料不足/失敗：{len(history_failed)} 檔"
    )
    _diag = df_support[[
        "stock_id", "stock_name", "market", "close", "support_price", "support_date",
        "rebound_pct", "vol_lot", "rev_yoy", "rev_ym", "history_days",
    ]].copy()
    _diag = make_display_df(_diag)
    st.caption("以下為已成功計算近半年支撐價的股票，包含未通過起漲幅條件者。")
    st.dataframe(_diag, use_container_width=True, hide_index=True)

if count == 0:
    st.warning(
        f"⚠️ 已成功計算 {len(df_support)} 檔支撐價，但自底部起漲幅 ≤ {rebound_max:.0f}% 後無符合。"
    )
    _near = df_support.sort_values("rebound_pct").head(20)
    if not _near.empty:
        st.caption("以下為距離底部支撐較近的前 20 檔（供調整條件參考）：")
        st.dataframe(make_display_df(_near), use_container_width=True, hide_index=True)
    st.stop()

st.subheader(f"📋 底部剛起漲名單（共 {count} 檔，以自底部漲幅由低到高排序）")

try:
    _price_date_raw = raw_twse_price[0].get("Date", "")
    if len(_price_date_raw) == 7:
        _py, _pm, _pd = int(_price_date_raw[:3]) + 1911, _price_date_raw[3:5], _price_date_raw[5:7]
        _date_str = f"{_py}/{_pm}/{_pd}"
    else:
        _date_str = _price_date_raw
    st.caption(
        f"📅 最新股價/成交量資料日期：{_date_str}（TWSE 最近交易日）"
        f"｜支撐價計算區間：{start_str} ~ {end_str}"
    )
except Exception:
    pass

display_df = make_display_df(df_result)
st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "股票代碼": st.column_config.TextColumn("股票代碼", width="small"),
        "股票名稱": st.column_config.TextColumn("股票名稱", width="medium"),
        "市場": st.column_config.TextColumn("市場", width="small"),
        "收盤價(元)": st.column_config.NumberColumn("收盤價(元)", format="%.2f"),
        "近半年支撐價(元)": st.column_config.NumberColumn("近半年支撐價(元)", format="%.2f"),
        "支撐日期": st.column_config.TextColumn("支撐日期", width="small"),
        "自底部漲幅(%)": st.column_config.NumberColumn("自底部漲幅(%)", format="%.2f"),
        "前一日成交量(張)": st.column_config.NumberColumn("前一日成交量(張)", format="%d"),
        "單月營收年增率(%)": st.column_config.NumberColumn("單月營收年增率(%)", format="%.2f"),
        "最新營收年月": st.column_config.TextColumn("最新營收年月", width="small"),
        "去年全年EPS(元)": st.column_config.NumberColumn("去年全年EPS(元)", format="%.2f"),
        "歷史交易日數": st.column_config.NumberColumn("歷史交易日數", format="%d"),
    },
)

csv = dataframe_to_csv_bytes(display_df)
st.download_button(
    "⬇️ 下載 CSV（Excel 可直接開啟）", csv,
    f"底部剛起漲選股_{datetime.today().strftime('%Y%m%d')}.csv", "text/csv",
)

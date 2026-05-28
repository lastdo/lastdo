import os
import time
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from _app_common import FINMIND_URL
from _finmind_api import (
    fetch_finmind_result,
    parse_eps_dataframe,
    parse_price_dataframe,
    get_result_message,
    get_retry_after,
    get_status_code,
    is_rate_limited,
)
from _export_utils import dataframe_to_csv_bytes
from _market_data import (
    REVENUE_COLUMNS,
    build_price_snapshot,
    build_recent_revenue_metrics,
    build_revenue_snapshot,
    latest_revenue_month,
    prev_roc_month,
)
from _market_api import fetch_json_tpex as fetch_json_tpex_base, fetch_json_twse as fetch_json_twse_base
from _public_valuation import attach_public_valuation, fetch_public_pe_ratios

load_dotenv()

# ------------------------------
# API 與常數
# ------------------------------
URL_TWSE_PRICE  = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
URL_TWSE_REV    = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
URL_TPEX_PRICE  = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
URL_TPEX_REV    = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"
SEASON_LINE_MAX_PREMIUM = 0.12  # 現價最多高於季線 12%

# ------------------------------
# 頁面設定
# ------------------------------
st.set_page_config(page_title="成長股篩選", page_icon="📈", layout="wide")

from _style import apply_style, page_header, render_global_navigation
apply_style()
page_header("📈", "成長股篩選", "從營收成長、成交量、股價與官方本益比找出合理估值的成長股。")


def render_page_positioning() -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            """
            **這頁看什麼**

            找出營收趨勢仍在延續、估值尚未完全失控，且股價沒有過度透支基本面的成長型股票。
            """
        )
    with col2:
        st.markdown(
            """
            **適合什麼情境**

            適合先從基本面動能中找方向，再檢查估值與價格位置是否仍有中期跟漲空間。
            """
        )
    with col3:
        st.markdown(
            """
            **篩選風格**

            邏輯屬於 **中性偏積極**，重視趨勢延續與估值紀律，不是單看單月營收爆發。
            """
        )


render_page_positioning()
st.caption("本頁優先判斷成長趨勢是否延續、價格是否先跑，避免把單月營收異常當成成長確認。")


def render_strategy_card() -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("策略核心", "成長延續")
    col2.metric("價格紀律", f"季線溢價 < {SEASON_LINE_MAX_PREMIUM * 100:.0f}%")
    col3.metric("資料主體", "官方 API")
    col4.metric("最終驗證", "FinMind 季線")
    st.caption("先用官方營收、成交量、股價與 PE 做主篩，再用季線限制避免價格過度透支。")


render_strategy_card()

# ------------------------------
# 側邊欄條件
# ------------------------------
with st.sidebar:
    render_global_navigation("growth_screener")
    st.markdown("---")
    st.header("篩選條件")
    st.divider()

    st.markdown("**資料設定**")
    finmind_token = st.text_input(
        "FinMind Token（選填）",
        value=os.getenv("FINMIND_TOKEN", ""),
        type="password",
        help="僅用於查詢季線（MA60）；本益比改採官方上市櫃API。",
    ).strip()

    st.markdown("**核心條件**")
    pe_max = st.number_input("本益比上限（倍）", value=20.0, min_value=1.0, max_value=500.0, step=1.0)
    rev_growth_min = st.number_input("近 2 月平均營收年增下限 (%)", value=20.0, min_value=-100.0, max_value=1000.0, step=1.0)
    vol_min = st.number_input("成交量下限（張）", value=1000, min_value=0, step=100)
    price_min = st.number_input("股價下限（元）", value=50.0, min_value=0.0, step=5.0)

    st.markdown("**操作**")
    run_btn = st.button("執行篩選", use_container_width=True, type="primary")
    if st.button("清除快取並重新整理", use_container_width=True):
        st.session_state.pop("screener_result", None)
        st.success("本頁結果已清除，請重新執行篩選。")
        st.stop()

    st.markdown("---")
    st.markdown("**資料來源**")
    st.caption("資料來源：股價 / 營收來自 TWSE + TPEX OpenAPI。")
    st.caption("資料來源：本益比來自官方上市櫃 API。")
    st.caption("本工具僅供研究參考，投資前請自行評估風險。")

def build_growth_alert_flags(result_df: pd.DataFrame, pe_limit: float, rev_floor: float) -> pd.DataFrame:
    result_df = result_df.copy()

    def _flags(row: pd.Series) -> str:
        flags = []
        avg_rev_yoy = pd.to_numeric(row.get("avg_rev_yoy"), errors="coerce")
        latest_rev_yoy = pd.to_numeric(row.get("latest_rev_yoy"), errors="coerce")
        prev_rev_yoy = pd.to_numeric(row.get("prev_rev_yoy"), errors="coerce")
        pe_ratio = pd.to_numeric(row.get("pe_ratio"), errors="coerce")
        season_line_premium = pd.to_numeric(row.get("season_line_premium"), errors="coerce")

        if (
            pd.notna(avg_rev_yoy)
            and pd.notna(latest_rev_yoy)
            and pd.notna(prev_rev_yoy)
            and avg_rev_yoy >= max(rev_floor + 10, 30)
            and latest_rev_yoy > 0
            and prev_rev_yoy > 0
            and abs(latest_rev_yoy - prev_rev_yoy) <= 20
        ):
            flags.append("趨勢續強")

        if (
            pd.notna(latest_rev_yoy)
            and pd.notna(prev_rev_yoy)
            and abs(latest_rev_yoy - prev_rev_yoy) >= 35
        ):
            flags.append("成長失真")

        if (
            pd.notna(avg_rev_yoy)
            and avg_rev_yoy >= max(rev_floor, 20)
            and pd.notna(pe_ratio)
            and pe_ratio >= max(pe_limit * 0.75, 18)
        ):
            flags.append("獲利未跟上")

        if (
            pd.notna(pe_ratio)
            and pe_ratio >= max(pe_limit * 0.9, 18)
            and pd.notna(avg_rev_yoy)
            and pe_ratio > avg_rev_yoy * 0.8
        ):
            flags.append("估值過熱")

        if (
            pd.notna(season_line_premium)
            and season_line_premium >= 0.08
            and pd.notna(latest_rev_yoy)
            and pd.notna(prev_rev_yoy)
            and latest_rev_yoy <= prev_rev_yoy + 5
        ):
            flags.append("價格領先")

        return "｜".join(flags) if flags else "正常"

    result_df["alert_flags"] = result_df.apply(_flags, axis=1)
    return result_df


def make_growth_display_df(result_df: pd.DataFrame) -> pd.DataFrame:
    display_df = result_df.rename(columns={
        "alert_flags": "警示標記",
        "stock_id": "股票代號",
        "stock_name": "股票名稱",
        "market": "市場",
        "close": "收盤價",
        "pe_ratio": "本益比",
        "pe_label": "PE口徑",
        "vol_lot": "成交量(張)",
        "avg_rev_yoy": "近2月平均營收年增(%)",
        "rev_months": "營收月份",
        "rev_cur": "當月營收",
        "rev_ly": "去年同月營收",
        "rev_ym": "最新營收月份",
    })[[
        "警示標記", "股票代號", "股票名稱", "市場", "收盤價", "本益比", "PE口徑",
        "近2月平均營收年增(%)", "營收月份", "成交量(張)", "當月營收", "去年同月營收", "最新營收月份",
    ]].copy()

    display_df["收盤價"] = pd.to_numeric(display_df["收盤價"], errors="coerce").round(2)
    display_df["本益比"] = pd.to_numeric(display_df["本益比"], errors="coerce").round(2)
    display_df["近2月平均營收年增(%)"] = pd.to_numeric(display_df["近2月平均營收年增(%)"], errors="coerce").round(2)
    display_df["成交量(張)"] = pd.to_numeric(display_df["成交量(張)"], errors="coerce").fillna(0).round(0).astype(int)
    display_df["當月營收"] = pd.to_numeric(display_df["當月營收"], errors="coerce").fillna(0).round(0).astype(int)
    display_df["去年同月營收"] = pd.to_numeric(display_df["去年同月營收"], errors="coerce").fillna(0).round(0).astype(int)
    return display_df.sort_values("收盤價", ascending=False).reset_index(drop=True)


def render_growth_alert_summary(display_df: pd.DataFrame) -> None:
    if display_df.empty or "警示標記" not in display_df.columns:
        return

    flattened = "｜".join(display_df["警示標記"].astype(str).tolist())
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("趨勢續強", flattened.count("趨勢續強"))
    col2.metric("成長失真", flattened.count("成長失真"))
    col3.metric("獲利未跟上", flattened.count("獲利未跟上"))
    col4.metric("估值過熱", flattened.count("估值過熱"))
    col5.metric("價格領先", flattened.count("價格領先"))


def render_growth_result_overview(display_df: pd.DataFrame, data_month: str) -> None:
    if display_df.empty or "警示標記" not in display_df.columns:
        return

    alerts = display_df["警示標記"].astype(str)
    positive_count = alerts.str.contains("趨勢續強", regex=False).sum()
    risk_count = alerts.str.contains("成長失真|獲利未跟上|估值過熱|價格領先", regex=True).sum()
    normal_count = (alerts == "正常").sum()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("候選檔數", f"{len(display_df)} 檔")
    col2.metric("正向訊號", int(positive_count))
    col3.metric("風險訊號", int(risk_count))
    col4.metric("正常觀察", int(normal_count), help=f"最新營收月份：{data_month or '-'}")


def render_growth_table(display_df: pd.DataFrame) -> None:
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "警示標記": st.column_config.TextColumn("警示標記", width="medium"),
            "股票代號": st.column_config.TextColumn("股票代號", width="small"),
            "股票名稱": st.column_config.TextColumn("股票名稱", width="medium"),
            "市場": st.column_config.TextColumn("市場", width="small"),
            "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
            "本益比": st.column_config.NumberColumn("本益比", format="%.2f"),
            "PE口徑": st.column_config.TextColumn("PE口徑", width="medium"),
            "近2月平均營收年增(%)": st.column_config.NumberColumn("近2月平均營收年增(%)", format="%.2f%%"),
            "營收月份": st.column_config.TextColumn("營收月份", width="medium"),
            "成交量(張)": st.column_config.NumberColumn("成交量(張)", format="%d"),
            "當月營收": st.column_config.NumberColumn("當月營收", format="%d"),
            "去年同月營收": st.column_config.NumberColumn("去年同月營收", format="%d"),
        },
    )


# ------------------------------
# 初始畫面 / 顯示上次結果
# ------------------------------
if not run_btn:
    # 尚未按下執行時，優先顯示 session_state 內的上次篩選結果。
    if "screener_result" in st.session_state:
        _r = st.session_state["screener_result"]
        st.info("顯示上次執行結果。若要更新，請按左側按鈕重新篩選。")
        _count = len(_r)
        _rev_ym = _r["rev_ym"].iloc[0] if _count > 0 else "-"
        st.subheader(f"成長股策略結果：{_count} 檔（最新營收月份：{_rev_ym}）")
        _disp = make_growth_display_df(build_growth_alert_flags(_r, pe_max, rev_growth_min))
        render_growth_result_overview(_disp, _rev_ym)
        render_growth_alert_summary(_disp)
        render_growth_table(_disp)
        _csv = dataframe_to_csv_bytes(_disp)
        st.download_button(
            "下載 CSV",
            _csv,
            f"成長股篩選_{datetime.today().strftime('%Y%m%d')}.csv",
            "text/csv",
        )
        st.stop()
    st.info("請先在左側設定篩選條件，然後點擊執行。")
    with st.expander("查看篩選條件與計算說明", expanded=True):
        st.markdown(f"""
| 條件 | 門檻 | 資料來源 |
|------|------|----------|
| 本益比 | < **{pe_max:.0f}** 倍 | 官方上市櫃 API |
| 近 2 月平均營收年增 | > **{rev_growth_min:.0f}%** | TWSE/TPEX OpenAPI 最新營收資料 |
| 成交量 | > **{int(vol_min):,}** 張 | TWSE/TPEX OpenAPI |
| 股價 | > **{price_min:.0f}** 元 | TWSE/TPEX OpenAPI |

**本頁本益比採官方上市櫃 API 口徑。**

本益比 = 官方上市櫃 API 提供之個股本益比

> 若公開資料來源暫時連不上，可能會出現查詢失敗，稍後再試即可。
> FinMind Token 只在最後查詢季線（MA60）時使用。
""")
    st.stop()

# ------------------------------
# 資料抓取與計算函式
# ------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_json_twse(url: str) -> list:
    return fetch_json_twse_base(url)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_json_tpex(url: str) -> list:
    return fetch_json_tpex_base(url)

@st.cache_data(ttl=1800, show_spinner=False)
def get_finmind_ma60(symbol: str, token: str = "") -> tuple[float | None, int | None, str]:
    """取得個股最新 60 日均線（季線）與查詢狀態。"""
    start_date = (datetime.today() - timedelta(days=140)).strftime("%Y-%m-%d")
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": start_date,
        "end_date": datetime.today().strftime("%Y-%m-%d"),
    }
    if token:
        params["token"] = token
    try:
        time.sleep(1.2)
        result = fetch_finmind_result(params, timeout=20)
        status = result.get("status")
        msg = get_result_message(result)
        status_code = get_status_code(result)
        if status_code != 200 or not result.get("data"):
            return None, status_code, msg
        df = parse_price_dataframe(result)
        if df.empty or "close" not in df.columns:
            return None, status_code, msg
        df = df.sort_values("date").reset_index(drop=True)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        ma = df["close"].rolling(60, min_periods=60).mean().iloc[-1]
        if pd.isna(ma):
            return None, status_code, msg
        return float(ma), status_code, msg
    except Exception as e:
        return None, None, str(e)


# ------------------------------
# Step 1：下載股價與營收原始資料
# ------------------------------
progress = st.progress(0, text="開始整理資料...")

progress.progress(5, text="正在下載股價資料（TWSE）...")
try:
    raw_twse_price = fetch_json_twse(URL_TWSE_PRICE)
except Exception as e:
    st.error(f"下載 TWSE 股價資料失敗：{e}"); st.stop()

progress.progress(18, text="正在下載股價資料（TPEX）...")
try:
    raw_tpex_price = fetch_json_tpex(URL_TPEX_PRICE)
except Exception as e:
    st.error(f"下載 TPEX 股價資料失敗：{e}"); st.stop()

progress.progress(35, text="正在下載營收資料（TWSE）...")
try:
    raw_twse_rev = fetch_json_twse(URL_TWSE_REV)
except Exception as e:
    st.error(f"下載 TWSE 營收資料失敗：{e}"); st.stop()

progress.progress(52, text="正在下載營收資料（TPEX）...")
try:
    raw_tpex_rev = fetch_json_tpex(URL_TPEX_REV)
except Exception as e:
    st.error(f"下載 TPEX 營收資料失敗：{e}"); st.stop()

progress.progress(65, text="正在整理候選名單...")

# ------------------------------
# Step 2：整理股價資料（TWSE + TPEX）
# ------------------------------
df_price = build_price_snapshot(raw_twse_price, raw_tpex_price)

# ------------------------------
# Step 3：整理營收資料（TWSE + TPEX）
# ------------------------------
df_rev = build_revenue_snapshot(raw_twse_rev, raw_tpex_rev)
_prev_ym = prev_roc_month(latest_revenue_month(df_rev))

if _prev_ym:
    progress.progress(65, text=f"補抓前一月營收資料（{_prev_ym}）...")
    _prev_parts = []
    for _url, _fn in [(URL_TWSE_REV, fetch_json_twse), (URL_TPEX_REV, fetch_json_tpex)]:
        try:
            _raw_p = _fn(f"{_url}?yearmonth={_prev_ym}")
            _df_p = pd.DataFrame(_raw_p)
            if not _df_p.empty and all(k in _df_p.columns for k in REVENUE_COLUMNS):
                _df_p = _df_p.rename(columns=REVENUE_COLUMNS)[list(REVENUE_COLUMNS.values())].copy()
                _prev_parts.append(_df_p)
        except Exception:
            pass
    if _prev_parts:
        _df_prev = pd.concat(_prev_parts, ignore_index=True)
        for _c in ["rev_yoy", "rev_cur", "rev_ly"]:
            _df_prev[_c] = pd.to_numeric(_df_prev[_c], errors="coerce")
        _df_prev["stock_id"] = _df_prev["stock_id"].astype(str).str.strip()
        _df_prev["rev_ym"] = _df_prev["rev_ym"].astype(str).str.strip().str.replace("/", "", regex=False)
        _df_prev = _df_prev.dropna(subset=["rev_yoy"])
        # 部分 API 會忽略 yearmonth 參數，因此這裡再手動篩一次月份。
        _df_prev = _df_prev[_df_prev["rev_ym"] == _prev_ym]
        if not _df_prev.empty:
            df_rev = pd.concat([df_rev, _df_prev], ignore_index=True)

# 只取每檔股票最近 2 個月的營收年增率，計算平均 YoY 與月份字串。
df_rev_final = build_recent_revenue_metrics(df_rev, months=2)

# ------------------------------
# Step 4：依營收、成交量、股價做初步篩選
# ------------------------------
df_merged = df_price.merge(df_rev_final, on="stock_id", how="inner")

df_candidates = df_merged[
    (df_merged["avg_rev_yoy"] > rev_growth_min)
    & (df_merged["vol_lot"]   > vol_min)
    & (df_merged["close"]     > price_min)
].copy().reset_index(drop=True)

n_candidates = len(df_candidates)
progress.progress(70, text=f"完成初步篩選：{n_candidates} 檔")

if n_candidates == 0:
    progress.progress(100, text="完成")
    st.warning("沒有股票符合營收/成交量/股價條件，請放寬條件後再試。")
    st.stop()


# 用官方上市櫃本益比建立估值資料。
progress.progress(71, text="抓取官方上市櫃本益比...")
df_public_pe = fetch_public_pe_ratios()
if df_public_pe.empty:
    progress.progress(100, text="完成")
    st.error("官方上市櫃本益比資料目前抓取失敗，無法套用 PE 條件，請稍後再試。")
    st.stop()
df_candidates = attach_public_valuation(df_candidates, df_public_pe)

df_candidates["_pe_sort"] = df_candidates["pe_ratio"].fillna(pe_max)
df_candidates = df_candidates.sort_values(
    ["_pe_sort", "avg_rev_yoy", "vol_lot"],
    ascending=[True, False, False],
).drop(columns=["_pe_sort"]).reset_index(drop=True)

n_candidates = len(df_candidates)
progress.progress(82, text=f"候選股 {n_candidates} 檔，套用官方本益比條件...")

df_result = df_candidates[
    df_candidates["pe_ratio"].notna() & (df_candidates["pe_ratio"] < pe_max)
].copy().sort_values("avg_rev_yoy", ascending=False).reset_index(drop=True)

if df_result.empty:
    progress.progress(100, text="完成")
    st.warning(f"候選股 {n_candidates} 檔中，沒有股票符合本益比 < {pe_max:.0f}。")
    df_no_pe = df_candidates[df_candidates["pe_ratio"].notna()].sort_values("pe_ratio")
    if not df_no_pe.empty:
        st.caption("以下為通過其他條件但未通過本益比門檻的股票（前 20 檔）。")
        st.dataframe(
            df_no_pe[["stock_id", "stock_name", "market", "close", "pe_ratio", "avg_rev_yoy"]].head(20),
            use_container_width=True,
            hide_index=True,
        )
    st.stop()

progress.progress(94, text=f"查詢季線條件（FinMind，{len(df_result)} 檔）...")
ma60_results = df_result["stock_id"].apply(lambda sid: get_finmind_ma60(sid, finmind_token))
df_result["ma60"] = ma60_results.apply(lambda x: x[0])
df_result["ma60_status"] = ma60_results.apply(lambda x: x[1])
df_result["ma60_msg"] = ma60_results.apply(lambda x: x[2])
df_result["season_line_premium"] = (
    (pd.to_numeric(df_result["close"], errors="coerce") / pd.to_numeric(df_result["ma60"], errors="coerce")) - 1
)

ma60_rate_limited = df_result["ma60_status"].isin([402, 403, 429]).sum()
if ma60_rate_limited > 0:
    _sample_ma60 = df_result[df_result["ma60_status"].isin([402, 403, 429])][
        ["stock_id", "stock_name", "ma60_status", "ma60_msg"]
    ].head(10)
    progress.progress(100, text="FinMind 季線查詢受限")
    st.error(
        f"FinMind 季線資料查詢受限：基本面通過後剩 {len(df_result)} 檔，"
        f"但仍有 {ma60_rate_limited} 檔在查 MA60 時收到 402/403/429。"
        "請稍後再試或清除快取後重跑。"
    )
    if not _sample_ma60.empty:
        st.caption("以下為部分受限股票：")
        st.dataframe(_sample_ma60, use_container_width=True, hide_index=True)
    st.stop()

df_result = df_result[
    df_result["ma60"].notna()
    & (df_result["close"] <= df_result["ma60"] * (1 + SEASON_LINE_MAX_PREMIUM))
].copy().sort_values("avg_rev_yoy", ascending=False).reset_index(drop=True)

progress.progress(100, text="篩選完成")

# 把結果存入 session_state，讓下載 CSV 或 rerun 後仍可直接顯示。
st.session_state["screener_result"] = df_result

# ------------------------------
# 結果顯示
# ------------------------------
count = len(df_result)
rev_ym = df_result["rev_ym"].iloc[0] if count > 0 else "-"

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("結果數量", f"{count} 檔")
col2.metric("本益比", f"< {pe_max:.0f}")
col3.metric("近 2 月營收年增", f"> {rev_growth_min:.0f}%")
col4.metric("成交量", f"> {int(vol_min):,} 張")
col5.metric("股價", f"> {price_min:.0f}")
col6.metric("PE 口徑", "官方API")

st.divider()

if count == 0:
    st.warning("通過本益比條件的股票，在季線 12% 條件下全數被排除。")
    st.stop()

st.subheader(f"成長股策略結果：{count} 檔（最新營收月份：{rev_ym}）")

# 顯示 TWSE 股價資料日期，方便確認本次篩選使用的交易日。
try:
    _price_date_raw = raw_twse_price[0].get("Date", "")
    if len(_price_date_raw) == 7:  # 民國日期格式，例如 1150512
        _y, _m, _d = int(_price_date_raw[:3]) + 1911, _price_date_raw[3:5], _price_date_raw[5:7]
        st.caption(f"股價資料日期：{_y}/{_m}/{_d}（TWSE）")
except Exception:
    pass

display_df = make_growth_display_df(build_growth_alert_flags(df_result, pe_max, rev_growth_min))
render_growth_result_overview(display_df, rev_ym)
render_growth_alert_summary(display_df)
render_growth_table(display_df)

csv_bytes = dataframe_to_csv_bytes(display_df)
st.download_button(
    label="下載 CSV",
    data=csv_bytes,
    file_name=f"成長股篩選_{datetime.today().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

st.divider()
st.caption("資料來源：股價/營收來自 TWSE + TPEX OpenAPI；本益比來自官方上市櫃口徑。")
st.caption("本工具僅供研究參考，請自行評估投資風險。")


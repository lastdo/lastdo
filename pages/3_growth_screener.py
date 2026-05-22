import os
import time
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from _app_common import FINMIND_URL
from _export_utils import dataframe_to_csv_bytes

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
page_header("📈", "成長股篩選", "從營收成長、成交量、股價與去年全年 EPS 找出合理本益比的成長股。")

# ------------------------------
# 側邊欄條件
# ------------------------------
with st.sidebar:
    render_global_navigation("growth_screener")
    st.markdown("---")
    st.header("篩選條件")
    st.divider()

    finmind_token = st.text_input(
        "FinMind Token",
        value=os.getenv("FINMIND_TOKEN", ""),
        type="password",
        help="用於查詢 EPS 與計算本益比；若 API 限流，建議降低查詢頻率或稍後再試。",
    ).strip()

    pe_max = st.number_input("本益比上限（倍）", value=20.0, min_value=1.0, max_value=500.0, step=1.0)
    last_yr_eps_min = st.number_input("去年全年 EPS 下限（元）", value=5.0, min_value=0.0, max_value=500.0, step=0.5,
        help="去年全年 EPS 會使用最近完整 4 季加總；需要 FinMind Token 才能查詢。")
    rev_growth_min = st.number_input("近 2 月平均營收年增下限 (%)", value=20.0, min_value=-100.0, max_value=1000.0, step=1.0)
    vol_min = st.number_input("成交量下限（張）", value=1000, min_value=0, step=100)
    price_min = st.number_input("股價下限（元）", value=50.0, min_value=0.0, step=5.0)

    run_btn = st.button("執行篩選", use_container_width=True, type="primary")
    if st.button("清除快取並重新整理", use_container_width=True):
        st.cache_data.clear()
        st.success("快取已清除，請重新執行篩選。")
        st.stop()

    st.markdown("---")
    st.caption("資料來源：股價 / 營收來自 TWSE + TPEX OpenAPI。")
    st.caption("資料來源：EPS 來自 FinMind（需要 Token）。")
    st.caption("本工具僅供研究參考，投資前請自行評估風險。")

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
        try:
            _price_date_raw = _r.attrs.get("price_date", "") if hasattr(_r, "attrs") else ""
        except Exception:
            _price_date_raw = ""
        _disp = _r.rename(columns={
            "stock_id": "股票代號",
            "stock_name": "股票名稱",
            "market": "市場",
            "close": "收盤價",
            "pe_ratio": "本益比",
            "pe_label": "EPS口徑",
            "vol_lot": "成交量(張)",
            "avg_rev_yoy": "近2月平均營收年增(%)",
            "rev_months": "營收月份",
            "rev_cur": "當月營收",
            "rev_ly": "去年同月營收",
            "rev_ym": "最新營收月份",
            "prev_year_eps": "去年全年EPS",
        })[["股票代號","股票名稱","市場","收盤價","本益比","EPS口徑",
            "去年全年EPS","近2月平均營收年增(%)","營收月份","成交量(張)",
            "當月營收","去年同月營收","最新營收月份"]]
        _disp["收盤價"] = _disp["收盤價"].round(2)
        _disp["本益比"] = _disp["本益比"].round(2)
        _disp["去年全年EPS"] = pd.to_numeric(_disp["去年全年EPS"], errors="coerce").round(2)
        _disp["近2月平均營收年增(%)"] = _disp["近2月平均營收年增(%)"].round(2)
        _disp["成交量(張)"] = _disp["成交量(張)"].round(0).astype(int)
        _disp["當月營收"] = pd.to_numeric(_disp["當月營收"], errors="coerce").fillna(0).round(0).astype(int)
        _disp["去年同月營收"] = pd.to_numeric(_disp["去年同月營收"], errors="coerce").fillna(0).round(0).astype(int)
        _disp = _disp.sort_values("收盤價", ascending=False).reset_index(drop=True)
        st.dataframe(_disp, use_container_width=True, hide_index=True)
        _csv = dataframe_to_csv_bytes(_disp)
        st.download_button("下載 CSV", _csv,
            f"growth_screener_{datetime.today().strftime('%Y%m%d')}.csv", "text/csv")
        st.stop()
    st.info("請先在左側設定篩選條件，然後點擊執行。")
    with st.expander("查看篩選條件與計算說明", expanded=True):
        st.markdown(f"""
| 條件 | 門檻 | 資料來源 |
|------|------|----------|
| 本益比 | < **{pe_max:.0f}** 倍 | FinMind EPS 與推估全年 EPS |
| 去年全年 EPS | > **{last_yr_eps_min:.1f}** 元 | FinMind 最近完整 4 季 EPS 加總 |
| 近 2 月平均營收年增 | > **{rev_growth_min:.0f}%** | TWSE/TPEX OpenAPI 最新營收資料 |
| 成交量 | > **{int(vol_min):,}** 張 | TWSE/TPEX OpenAPI |
| 股價 | > **{price_min:.0f}** 元 | TWSE/TPEX OpenAPI |

**本益比是以 AI 分析頁相同的推估全年 EPS 口徑計算。**

推估全年 EPS = 今年已公告季度 EPS + 去年同期未公告季度 EPS

本益比 = 收盤價 / 推估全年 EPS

> 若公開資料來源暫時連不上，可能會出現查詢失敗，稍後再試即可。
> 若未提供 FinMind Token，系統無法查詢 EPS，也就無法計算本益比。
""")
    st.stop()

if not finmind_token:
    st.error("請先輸入 FinMind Token，才能查詢 EPS 與計算本益比。")
    st.stop()

# ------------------------------
# 資料抓取與計算函式
# ------------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_json_twse(url: str) -> list:
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_json_tpex(url: str) -> list:
    """抓取 TPEX JSON，使用較長 timeout 與簡單重試。"""
    headers = {"User-Agent": "Mozilla/5.0"}
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=90, headers=headers, stream=False)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))  # 2s, 4s, 6s
    raise last_err


_MONTH_TO_Q = {3: 1, 6: 2, 9: 3, 12: 4}


def calc_forward_pe(close_price: float, eps_q: pd.DataFrame):
    """用最新已公告季度 EPS 推估全年本益比。"""
    if eps_q is None or eps_q.empty:
        return None, "EPS 資料不足"

    q = eps_q.copy()
    q["year"] = q["date"].dt.year
    q["month"] = q["date"].dt.month
    latest_year = int(q["year"].max())
    latest_year_q = q[q["year"] == latest_year].sort_values("date")
    num_q_latest = len(latest_year_q)
    prev_year = latest_year - 1
    prev_year_q = q[q["year"] == prev_year].sort_values("date")

    latest_months = set(latest_year_q["month"].tolist())
    remaining_prev = prev_year_q[~prev_year_q["month"].isin(latest_months)]
    forward_eps = 0.0
    for _, r in latest_year_q.iterrows():
        forward_eps += float(r["eps"])
    for _, r in remaining_prev.iterrows():
        forward_eps += float(r["eps"])

    if forward_eps <= 0:
        return None, f"推估 EPS={forward_eps:.2f} <= 0"

    pe = close_price / forward_eps
    if num_q_latest >= 4:
        label = f"{latest_year} 全年"
    else:
        rem_start = num_q_latest + 1
        cur_part = f"{latest_year}Q1" if num_q_latest == 1 else f"{latest_year}Q1-Q{num_q_latest}"
        prev_part = f"{prev_year}Q{rem_start}" if rem_start == 4 else f"{prev_year}Q{rem_start}-Q4"
        label = f"{cur_part}+{prev_part}"
    return pe, label


def calc_prev_year_eps(eps_q: pd.DataFrame):
    """回傳最近一個完整年度的 EPS 加總。"""
    if eps_q is None or eps_q.empty:
        return None
    q = eps_q.copy()
    q["year"] = q["date"].dt.year
    cur_year = datetime.today().year  # 略過尚未完整公告的當年度資料。
    for yr in sorted(q["year"].unique(), reverse=True):
        if yr >= cur_year:
            continue  # 只採用已完整結束的年度，避免用到未完整年度。
        yr_data = q[q["year"] == yr]
        if len(yr_data) >= 4:
            return float(yr_data["eps"].sum())
    return None


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_public_pe_ratios() -> pd.DataFrame:
    """抓取 TWSE/TPEX 當日公開本益比，用來先縮小 FinMind 查詢名單。"""
    frames = []

    try:
        raw_twse = fetch_json_twse(URL_TWSE_PRICE)
        df_twse = pd.DataFrame(raw_twse)
        if {"Code", "PEratio"}.issubset(df_twse.columns):
            frames.append(
                df_twse[["Code", "PEratio"]].rename(
                    columns={"Code": "stock_id", "PEratio": "pe_ratio_public"}
                )
            )
    except Exception:
        pass

    try:
        raw_tpex = fetch_json_tpex(URL_TPEX_PRICE)
        df_tpex = pd.DataFrame(raw_tpex)
        if {"SecuritiesCompanyCode", "PriceEarningRatio"}.issubset(df_tpex.columns):
            frames.append(
                df_tpex[["SecuritiesCompanyCode", "PriceEarningRatio"]].rename(
                    columns={
                        "SecuritiesCompanyCode": "stock_id",
                        "PriceEarningRatio": "pe_ratio_public",
                    }
                )
            )
    except Exception:
        pass

    if not frames:
        return pd.DataFrame(columns=["stock_id", "pe_ratio_public"])

    df = pd.concat(frames, ignore_index=True)
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df["pe_ratio_public"] = (
        df["pe_ratio_public"].astype(str).str.replace(",", "", regex=False).str.strip()
    )
    df["pe_ratio_public"] = pd.to_numeric(df["pe_ratio_public"], errors="coerce")
    df.loc[df["pe_ratio_public"] <= 0, "pe_ratio_public"] = pd.NA
    return df.drop_duplicates("stock_id")


@st.cache_data(ttl=1800, show_spinner=False)
def get_finmind_eps(symbol: str, token: str) -> pd.DataFrame:
    """查詢個股近三年季 EPS。"""
    start_year = datetime.today().year - 3
    params = {
        "dataset": "TaiwanStockFinancialStatements",
        "data_id": symbol,
        "start_date": f"{start_year}-01-01",
        "end_date": datetime.today().strftime("%Y-%m-%d"),
        "token": token,
    }
    try:
        time.sleep(2.2)
        resp = requests.get(FINMIND_URL, params=params, timeout=20)
        result = resp.json()
        status = result.get("status")
        msg = str(result.get("msg") or result.get("message") or result.get("error") or "")
        status_code = int(status) if str(status).isdigit() else status
        if status_code in (402, 403, 429) or "ban" in msg.lower() or "rate" in msg.lower():
            raise RuntimeError(
                f"FINMIND_LIMIT:{status}:{result.get('retry_after', '?')}:{msg}"
            )
        if status_code != 200 or not result.get("data"):
            return pd.DataFrame()
        df = pd.DataFrame(result["data"])
        df = df[df["type"] == "EPS"].copy()
        if df.empty:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"])
        df["eps"] = pd.to_numeric(df["value"], errors="coerce")
        return df[["date", "eps"]].sort_values("date").reset_index(drop=True)
    except RuntimeError:
        raise
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def get_finmind_ma60(symbol: str, token: str) -> tuple[float | None, int | None, str]:
    """取得個股最新 60 日均線（季線）與查詢狀態。"""
    start_date = (datetime.today() - timedelta(days=140)).strftime("%Y-%m-%d")
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": start_date,
        "end_date": datetime.today().strftime("%Y-%m-%d"),
        "token": token,
    }
    try:
        time.sleep(1.2)
        resp = requests.get(FINMIND_URL, params=params, timeout=20)
        result = resp.json()
        status = result.get("status")
        msg = str(result.get("msg") or result.get("message") or result.get("error") or "")
        status_code = int(status) if str(status).isdigit() else status
        if status_code != 200 or not result.get("data"):
            return None, status_code, msg
        df = pd.DataFrame(result["data"])
        if df.empty or "close" not in df.columns:
            return None, status_code, msg
        df["date"] = pd.to_datetime(df["date"])
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
df_twse_p = pd.DataFrame(raw_twse_price)[["Code", "Name", "ClosingPrice", "TradeVolume"]].copy()
df_twse_p = df_twse_p.rename(columns={"Code": "stock_id", "Name": "stock_name",
                                       "ClosingPrice": "close", "TradeVolume": "vol_shares"})
df_twse_p["market"] = "TWSE"

df_tpex_p = pd.DataFrame(raw_tpex_price)[["SecuritiesCompanyCode", "CompanyName", "Close", "TradingShares"]].copy()
df_tpex_p = df_tpex_p.rename(columns={"SecuritiesCompanyCode": "stock_id", "CompanyName": "stock_name",
                                        "Close": "close", "TradingShares": "vol_shares"})
df_tpex_p["market"] = "TPEX"

df_price = pd.concat([df_twse_p, df_tpex_p], ignore_index=True)
df_price["close"] = pd.to_numeric(df_price["close"], errors="coerce")
df_price["vol_shares"] = pd.to_numeric(df_price["vol_shares"], errors="coerce")
df_price["vol_lot"] = df_price["vol_shares"] / 1000
df_price = df_price[["stock_id", "stock_name", "market", "close", "vol_lot"]].dropna()

# ------------------------------
# Step 3：整理營收資料（TWSE + TPEX）
# ------------------------------
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
df_rev["rev_yoy"] = pd.to_numeric(df_rev["rev_yoy"], errors="coerce")
df_rev["rev_cur"] = pd.to_numeric(df_rev["rev_cur"], errors="coerce")
df_rev["rev_ly"]  = pd.to_numeric(df_rev["rev_ly"],  errors="coerce")
df_rev = df_rev.dropna(subset=["rev_yoy"])

# 若最新月份不足兩個月，補抓前一個月資料，才能計算近 2 月平均營收年增。
def _prev_roc_ym(ym_str: str) -> str:
    """將民國年月（如 11504 或 202604）轉成前一個月份。"""
    try:
        s = str(ym_str).strip().replace("/", "")
        if len(s) == 5:           # 民國格式：11504
            roc_y, m = int(s[:3]), int(s[3:])
        elif len(s) == 6:         # 西元格式：202604
            roc_y, m = int(s[:4]) - 1911, int(s[4:])
        else:
            return ""
        m -= 1
        if m == 0:
            m, roc_y = 12, roc_y - 1
        return f"{roc_y}{m:02d}"
    except Exception:
        return ""

_latest_ym_list = df_rev["rev_ym"].dropna().unique().tolist()
_prev_ym = _prev_roc_ym(
    pd.Series(_latest_ym_list).value_counts().index[0]
) if _latest_ym_list else ""

if _prev_ym:
    progress.progress(65, text=f"補抓前一月營收資料（{_prev_ym}）...")
    _prev_parts = []
    for _url, _fn in [(URL_TWSE_REV, fetch_json_twse), (URL_TPEX_REV, fetch_json_tpex)]:
        try:
            _raw_p = _fn(f"{_url}?yearmonth={_prev_ym}")
            _df_p = pd.DataFrame(_raw_p)
            if not _df_p.empty and all(k in _df_p.columns for k in rev_col_map):
                _df_p = _df_p.rename(columns=rev_col_map)[list(rev_col_map.values())].copy()
                _prev_parts.append(_df_p)
        except Exception:
            pass
    if _prev_parts:
        _df_prev = pd.concat(_prev_parts, ignore_index=True)
        for _c in ["rev_yoy", "rev_cur", "rev_ly"]:
            _df_prev[_c] = pd.to_numeric(_df_prev[_c], errors="coerce")
        _df_prev = _df_prev.dropna(subset=["rev_yoy"])
        # 部分 API 會忽略 yearmonth 參數，因此這裡再手動篩一次月份。
        _df_prev = _df_prev[
            _df_prev["rev_ym"].astype(str).str.strip().str.replace("/", "") == _prev_ym
        ]
        if not _df_prev.empty:
            df_rev = pd.concat([df_rev, _df_prev], ignore_index=True)

# 只取每檔股票最近 2 個月的營收年增率，計算平均 YoY 與月份字串。
df_rev_s = df_rev.sort_values(["stock_id", "rev_ym"], ascending=[True, False])
df_rev_top2 = df_rev_s.groupby("stock_id").head(2)
df_rev_avg = df_rev_top2.groupby("stock_id", as_index=False).agg(
    avg_rev_yoy=("rev_yoy", "mean"),
    rev_months=("rev_ym", lambda x: "/".join(sorted(x.tolist(), reverse=True))),
)
# 保留每檔股票最新一筆營收，並合併近 2 月平均營收年增資訊。
df_rev_latest = df_rev_s.groupby("stock_id", as_index=False).first()
df_rev_final = df_rev_latest.merge(
    df_rev_avg[["stock_id", "avg_rev_yoy", "rev_months"]], on="stock_id", how="left"
)

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


# 用公開本益比排序查詢順序，但不排除任何候選股。
progress.progress(71, text="用公開本益比排序 FinMind 查詢順序...")
df_public_pe = fetch_public_pe_ratios()
df_candidates = df_candidates.merge(df_public_pe, on="stock_id", how="left")

df_finmind_targets = df_candidates.copy()
df_finmind_targets["_pe_sort"] = df_finmind_targets["pe_ratio_public"].fillna(pe_max)
df_finmind_targets = df_finmind_targets.sort_values(
    ["_pe_sort", "avg_rev_yoy", "vol_lot"],
    ascending=[True, False, False],
).drop(columns=["_pe_sort"]).reset_index(drop=True)

df_candidates = df_finmind_targets.copy().reset_index(drop=True)
n_candidates = len(df_candidates)

# ------------------------------
# Step 4.5：查詢候選股去年全年 EPS，作為後續基本面門檻
# ------------------------------
progress.progress(74, text=f"候選股 {n_candidates} 檔，開始查詢去年全年 EPS（FinMind）...")

# ------------------------------
# Step 5：低速查詢 FinMind EPS，計算推估本益比
# ------------------------------
eps_bar = st.progress(0, text=f"正在查詢 EPS：0 / {n_candidates} 檔（低速模式）...")

results = []
errors = []
_banned_msg = ""

for done_count, (_, row) in enumerate(df_candidates.iterrows(), start=1):
    sid_done = row["stock_id"]
    try:
        eps_q = get_finmind_eps(sid_done, finmind_token)
        pe, pe_label = calc_forward_pe(float(row["close"]), eps_q)
        prev_eps = calc_prev_year_eps(eps_q)
        results.append(
            {
                "stock_id": sid_done,
                "pe_ratio": pe,
                "pe_label": pe_label,
                "prev_year_eps": prev_eps,
            }
        )
    except RuntimeError as e:
        err = str(e)
        if "FINMIND_LIMIT" in err:
            _banned_msg = err
            break
        errors.append((sid_done, err))
    except Exception as e:
        errors.append((sid_done, str(e)))

    eps_bar.progress(
        min(done_count / n_candidates, 1.0),
        text=f"正在查詢 EPS：{done_count} / {n_candidates} 檔"
    )

if _banned_msg and not results:
    _parts = _banned_msg.split(":", 3)
    _retry = _parts[2] if len(_parts) >= 3 else "?"
    try:
        _wait_min = int(_retry) // 60 + 1
    except Exception:
        _wait_min = "?"
    eps_bar.progress(1.0, text="FinMind 達到查詢上限")
    st.error(
        f"FinMind API 暫時限制此 IP，建議等待約 {_wait_min} 分鐘後再試。\n\n"
        f"若常發生，可降低同時查詢數或稍後重新執行。"
    )
    st.stop()

if _banned_msg:
    _parts = _banned_msg.split(":", 3)
    _status = _parts[1] if len(_parts) >= 2 else "?"
    progress.progress(100, text="FinMind EPS 查詢受限")
    st.error(
        f"FinMind EPS 查詢途中收到狀態碼 {_status}，本次只有部分股票完成，結果不完整，已停止避免誤判。"
    )
    st.stop()

eps_bar.progress(1.0, text="EPS 查詢完成")

if errors:
    _err_preview = "；".join(f"{sid}: {msg}" for sid, msg in errors[:3])
    st.warning(f"共有 {len(errors)} 檔 EPS 查詢失敗。範例：{_err_preview}")

df_pe = pd.DataFrame(results)
df_all = df_candidates.merge(df_pe, on="stock_id", how="left")

# 先套用去年全年 EPS 門檻。
df_after_eps = df_all[
    df_all["prev_year_eps"].notna() & (df_all["prev_year_eps"] > last_yr_eps_min)
].copy().reset_index(drop=True)

n_after_eps = len(df_after_eps)
progress.progress(88, text=f"EPS 篩選完成：{n_after_eps} 檔")

if n_after_eps == 0:
    progress.progress(100, text="完成")
    st.warning(f"候選股 {n_candidates} 檔中，沒有股票通過去年 EPS > {last_yr_eps_min:.1f} 的條件。")
    st.stop()

# 再套用本益比上限。
df_result = df_after_eps[
    df_after_eps["pe_ratio"].notna() & (df_after_eps["pe_ratio"] < pe_max)
].copy().sort_values("avg_rev_yoy", ascending=False).reset_index(drop=True)

if df_result.empty:
    progress.progress(100, text="完成")
    st.warning(f"通過 EPS 條件的 {n_after_eps} 檔中，沒有股票符合本益比 < {pe_max:.0f}。")
    df_no_pe = df_after_eps[df_after_eps["pe_ratio"].notna()].sort_values("pe_ratio")
    if not df_no_pe.empty:
        st.caption("以下為已通過 EPS 條件但未通過本益比門檻的股票（前 20 檔）。")
        st.dataframe(
            df_no_pe[["stock_id", "stock_name", "market", "close", "pe_ratio", "prev_year_eps", "avg_rev_yoy"]].head(20),
            use_container_width=True,
            hide_index=True,
        )
    st.stop()

# 最後才查季線，讓 FinMind 股價查詢量降到最小。
progress.progress(94, text=f"查詢季線條件（FinMind，{len(df_result)} 檔）...")
ma60_results = df_result["stock_id"].apply(lambda sid: get_finmind_ma60(sid, finmind_token))
df_result["ma60"] = ma60_results.apply(lambda x: x[0])
df_result["ma60_status"] = ma60_results.apply(lambda x: x[1])
df_result["ma60_msg"] = ma60_results.apply(lambda x: x[2])

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
col3.metric("去年 EPS", f"> {last_yr_eps_min:.1f}")
col4.metric("近 2 月營收年增", f"> {rev_growth_min:.0f}%")
col5.metric("成交量", f"> {int(vol_min):,} 張")
col6.metric("股價", f"> {price_min:.0f}")

st.divider()

if count == 0:
    st.warning("通過 EPS 與本益比條件的股票，在季線 12% 條件下全數被排除。")
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

display_df = df_result.rename(columns={
    "stock_id": "股票代號",
    "stock_name": "股票名稱",
    "market": "市場",
    "close": "收盤價",
    "pe_ratio": "本益比",
    "pe_label": "EPS口徑",
    "vol_lot": "成交量(張)",
    "avg_rev_yoy": "近2月平均營收年增(%)",
    "rev_months": "營收月份",
    "rev_cur": "當月營收",
    "rev_ly": "去年同月營收",
    "rev_ym": "最新營收月份",
    "prev_year_eps": "去年全年EPS",
})[[
    "股票代號", "股票名稱", "市場", "收盤價", "本益比", "EPS口徑",
    "去年全年EPS", "近2月平均營收年增(%)", "營收月份", "成交量(張)",
    "當月營收", "去年同月營收", "最新營收月份",
]]

display_df["收盤價"] = display_df["收盤價"].round(2)
display_df["本益比"] = display_df["本益比"].round(2)
display_df["去年全年EPS"] = pd.to_numeric(display_df["去年全年EPS"], errors="coerce").round(2)
display_df["近2月平均營收年增(%)"] = display_df["近2月平均營收年增(%)"].round(2)
display_df["成交量(張)"] = display_df["成交量(張)"].round(0).astype(int)
display_df["當月營收"] = pd.to_numeric(display_df["當月營收"], errors="coerce").fillna(0).round(0).astype(int)
display_df["去年同月營收"] = pd.to_numeric(display_df["去年同月營收"], errors="coerce").fillna(0).round(0).astype(int)
display_df = display_df.sort_values("收盤價", ascending=False).reset_index(drop=True)

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "股票代號": st.column_config.TextColumn("股票代號", width="small"),
        "股票名稱": st.column_config.TextColumn("股票名稱", width="medium"),
        "市場": st.column_config.TextColumn("市場", width="small"),
        "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
        "本益比": st.column_config.NumberColumn("本益比", format="%.2f"),
        "EPS口徑": st.column_config.TextColumn("EPS口徑", width="medium"),
        "去年全年EPS": st.column_config.NumberColumn("去年全年EPS", format="%.2f"),
        "近2月平均營收年增(%)": st.column_config.NumberColumn("近2月平均營收年增(%)", format="%.2f%%"),
        "營收月份": st.column_config.TextColumn("營收月份", width="medium"),
        "成交量(張)": st.column_config.NumberColumn("成交量(張)", format="%d"),
        "當月營收": st.column_config.NumberColumn("當月營收", format="%d"),
        "去年同月營收": st.column_config.NumberColumn("去年同月營收", format="%d"),
    },
)

csv_bytes = dataframe_to_csv_bytes(display_df)
st.download_button(
    label="下載 CSV",
    data=csv_bytes,
    file_name=f"growth_screener_{datetime.today().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

st.divider()
st.caption("資料來源：股價/營收來自 TWSE + TPEX OpenAPI；EPS 來自 FinMind。")
st.caption("本工具僅供研究參考，請自行評估投資風險。")


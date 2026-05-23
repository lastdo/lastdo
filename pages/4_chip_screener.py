import os
import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from _market_api import fetch_json_tpex as fetch_json_tpex_base, fetch_json_twse as fetch_json_twse_base
from _public_valuation import attach_public_valuation, fetch_public_pe_ratios

load_dotenv()

# ─────────────────────────────────────────────
# API 端點
# ─────────────────────────────────────────────
URL_TWSE_PRICE = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
URL_TPEX_PRICE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
from _app_common import FINMIND_URL
from _export_utils import dataframe_to_csv_bytes
from _page_bootstrap import ROOT_DIR

# ─────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────
st.set_page_config(page_title="外資籌碼重壓選股器", page_icon="🏦", layout="wide")

from _style import apply_style, page_header, render_global_navigation
apply_style()
page_header("🏦", "外資籌碼重壓選股器", "策略：外資籌碼重壓 ｜ 上市＋上櫃 ｜ 近N日外資累積買超為主篩條件")

# ─────────────────────────────────────────────
# 側邊欄
# ─────────────────────────────────────────────
with st.sidebar:
    render_global_navigation("chip_screener")
    st.markdown("---")
    st.header("⚙️ 選股條件")
    st.divider()

    days_n = int(st.number_input(
        "近 N 日（交易日）", value=3, min_value=1, max_value=30, step=1,
        help="統計最近 N 個交易日的外資累積買超",
    ))
    foreign_buy_min = st.number_input(
        "外資累積買超 大於（張）", value=3000, min_value=0, step=100,
        help="近N日外資累積淨買超（買-賣），單位：張（1張=1000股）",
    )
    pe_max = st.number_input(
        "本益比 小於（倍）", value=20.0, min_value=1.0, max_value=500.0, step=1.0,
        help="使用官方上市櫃 API 提供的個股本益比。",
    )
    price_min = st.number_input("股價 大於（元）", value=50.0, min_value=0.0, step=5.0)
    vol_min   = st.number_input("當日成交量 大於（張）", value=1000, min_value=0, step=100)

    run_btn = st.button("🔍 開始選股", use_container_width=True, type="primary")
    if st.button("🗑️ 清除快取（強制重新抓資料）", use_container_width=True):
        st.session_state.pop("chip_screener_result", None)
        st.success("✅ 本頁結果已清除，請重新選股")
        st.stop()

    st.markdown("---")
    st.caption("📡 股價：TWSE + TPEX OpenAPI（免費）")
    st.caption("📡 外資買賣超：TWSE + TPEX（免費）｜ 本益比：官方上市櫃 API")
    st.caption("📢 本系統僅供學術研究，不構成投資建議")

# ─────────────────────────────────────────────
# 說明頁 / 恢復上次結果
# ─────────────────────────────────────────────
if not run_btn:
    if "chip_screener_result" in st.session_state:
        _r = st.session_state["chip_screener_result"]
        st.info("💡 顯示上次選股結果。如需重新選股請點擊「開始選股」。")
        _count = len(_r)
        st.subheader(f"📋 外資籌碼重壓名單（共 {_count} 檔）")
        _disp = _r.rename(columns={
            "stock_id":            "股票代碼",
            "stock_name":          "股票名稱",
            "market":              "市場",
            "close":               "收盤價(元)",
            "vol_lot":             "當日成交量(張)",
            "foreign_net_buy_lot": "外資近N日買超(張)",
            "pe_ratio":            "本益比(倍)",
            "pe_label":            "PE口徑",
        })[["股票代碼", "股票名稱", "市場", "收盤價(元)", "本益比(倍)", "PE口徑",
            "外資近N日買超(張)", "當日成交量(張)"]]
        _disp["收盤價(元)"]        = _disp["收盤價(元)"].round(2)
        _disp["本益比(倍)"]        = pd.to_numeric(_disp["本益比(倍)"], errors="coerce").round(2)
        _disp["外資近N日買超(張)"] = pd.to_numeric(_disp["外資近N日買超(張)"], errors="coerce").round(0).astype(int)
        _disp["當日成交量(張)"]    = _disp["當日成交量(張)"].round(0).astype(int)
        _disp = _disp.sort_values("收盤價(元)", ascending=False).reset_index(drop=True)
        st.dataframe(_disp, use_container_width=True, hide_index=True)
        _csv = dataframe_to_csv_bytes(_disp)
        st.download_button(
            "⬇️ 下載 CSV（Excel 可直接開啟）", _csv,
            f"外資籌碼重壓_{datetime.today().strftime('%Y%m%d')}.csv", "text/csv",
        )
        st.stop()
    st.info("👈 請在左側設定條件後，點擊「開始選股」")
    with st.expander("📖 選股條件與算法說明", expanded=True):
        st.markdown(f"""
| 條件 | 設定值 | 資料來源 |
|------|--------|---------|
| 近N日外資累積買超 | > **{foreign_buy_min:,.0f}** 張 | TWSE + TPEX 三大法人資料 |
| 本益比 | < **{pe_max:.0f}** 倍 | 官方上市櫃 API |
| 股價 | > **{price_min:.0f}** 元 | TWSE/TPEX OpenAPI（免費） |
| 當日成交量 | > **{int(vol_min):,}** 張 | TWSE/TPEX OpenAPI（免費） |

**外資累積買超算法：**

統計最近 {days_n} 個交易日內，外資（外資及陸資、外資自營商）每日淨買超（買入－賣出）之總和，單位換算為張（1張=1000股）。

**本益比算法：**

本益比 = 官方上市櫃 API 提供之個股本益比

近四季EPS = 收盤價 / 官方本益比

> 流程：先用免費 API 篩出通過股價、成交量條件的候選股，
> 再用免費 TWSE/TPEX 三大法人 API 取近N日外資買賣超，笻出達標候選股，
> 最後直接套用官方本益比，不再額外查 FinMind 季EPS。
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


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_twse_3insti(date_ymd: str) -> pd.DataFrame:
    """查詢 TWSE 三大法人個股買賣超（date_ymd: YYYYMMDD）
    回傳欄位：stock_id, foreign_net_shares（外資合計買賣超股數）
    """
    url = (f"https://www.twse.com.tw/fund/T86"
           f"?response=json&date={date_ymd}&selectType=ALLBUT0999")
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        result = resp.json()
        if result.get("stat") != "OK" or not result.get("data"):
            return pd.DataFrame()
        fields = result["fields"]
        df = pd.DataFrame(result["data"], columns=fields)
        # 用模糊比對找欄位，避免繁簡字差異（陸/陆）造成 KeyError
        col_f = next(
            (c for c in df.columns if "不含外資自營商" in c and "買賣超" in c),
            None,
        )
        col_fd = next((c for c in df.columns if "外資自營商買賣超" in c), None)
        if col_f is None:
            st.warning(f"⚠️ TWSE T86 找不到外資欄位，實際欄位：{list(df.columns)}")
            return pd.DataFrame()
        net = pd.to_numeric(df[col_f].str.replace(",", ""), errors="coerce").fillna(0)
        if col_fd:
            net = net + pd.to_numeric(df[col_fd].str.replace(",", ""), errors="coerce").fillna(0)
        df["foreign_net_shares"] = net
        df2 = df[["證券代號", "foreign_net_shares"]].rename(columns={"證券代號": "stock_id"})
        df2["stock_id"] = df2["stock_id"].str.strip()
        return df2
    except Exception as e:
        st.warning(f"⚠️ TWSE 三大法人 API 例外：{e}")
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_tpex_3insti(date_roc: str) -> pd.DataFrame:
    """查詢 TPEX 三大法人個股買賣超（date_roc: YYY/MM/DD 民國年）
    優先使用 OpenAPI，回傳欄位：stock_id, foreign_net_shares
    """
    # TPEX OpenAPI（較穩定）
    url_open = ("https://www.tpex.org.tw/openapi/v1/"
                "tpex_mainboard_3insti_quotes")
    try:
        resp = requests.get(url_open, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            raise ValueError("empty")
        df = pd.DataFrame(data)
        # 欄位：SecuritiesCompanyCode, ForeignInvestmentNetBuyShares, DealerHedgingNetBuyShares
        col_id  = next((c for c in df.columns if "Code" in c or "代號" in c or "代碼" in c), None)
        col_f   = next((c for c in df.columns if "ForeignInvestment" in c and "Net" in c and "Shares" in c), None)
        col_fd  = next((c for c in df.columns if "DealerHedging" in c and "Net" in c and "Shares" in c), None)
        if col_id is None or col_f is None:
            raise ValueError(f"欄位不符：{list(df.columns)}")
        net = pd.to_numeric(df[col_f].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
        if col_fd:
            net = net + pd.to_numeric(df[col_fd].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
        df2 = pd.DataFrame({"stock_id": df[col_id].astype(str).str.strip(), "foreign_net_shares": net})
        return df2
    except Exception:
        pass  # fallback 到舊版 web API

    url_old = ("https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
               f"3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={date_roc}&s=0,asc&o=json")
    try:
        resp = requests.get(url_old, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        j = resp.json()
        tables = j.get("tables", [])
        if not tables or not tables[0].get("data"):
            return pd.DataFrame()
        header = tables[0].get("fields", []) or tables[0].get("title", [])
        df = pd.DataFrame(tables[0]["data"])
        # 找外資相關欄（不含自營商）和外資自營商欄
        col_f  = next((i for i, h in enumerate(header) if "不含外資自營商" in str(h) and "買賣超" in str(h)), None)
        col_fd = next((i for i, h in enumerate(header) if "外資自營商" in str(h) and "不含" not in str(h)), None)
        if col_f is None:
            col_f = 4  # 預設欄位 index fallback
        if col_fd is None and df.shape[1] > 7:
            col_fd = 7
        net = pd.to_numeric(df[col_f].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
        if col_fd is not None:
            net = net + pd.to_numeric(df[col_fd].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
        df2 = pd.DataFrame({"stock_id": df[0].astype(str).str.strip(), "foreign_net_shares": net})
        return df2
    except Exception as e:
        st.warning(f"⚠️ TPEX 三大法人 API 例外：{e}")
        return pd.DataFrame()

# ─────────────────────────────────────────────
# Step 1：抓取股價（免費 API）
# ─────────────────────────────────────────────
progress = st.progress(0, text="🚀 準備中...")

progress.progress(5, text="📈 取得上市股價與成交量（TWSE）...")
try:
    raw_twse_price = fetch_json_twse(URL_TWSE_PRICE)
except Exception as e:
    st.error(f"❌ 上市股價 API 失敗：{e}"); st.stop()

progress.progress(15, text="📈 取得上櫃股價與成交量（TPEX）...")
try:
    raw_tpex_price = fetch_json_tpex(URL_TPEX_PRICE)
except Exception as e:
    st.error(f"❌ 上櫃股價 API 失敗：{e}"); st.stop()

progress.progress(25, text="🔧 整理股價資料並套用初步篩選...")

# ─────────────────────────────────────────────
# Step 2：整理股價+成交量
# ─────────────────────────────────────────────
df_twse_p = pd.DataFrame(raw_twse_price)[["Code", "Name", "ClosingPrice", "TradeVolume"]].copy()
df_twse_p = df_twse_p.rename(columns={
    "Code": "stock_id", "Name": "stock_name",
    "ClosingPrice": "close", "TradeVolume": "vol_shares",
})
df_twse_p["stock_id"] = df_twse_p["stock_id"].str.strip()
df_twse_p["market"] = "上市"

df_tpex_p = pd.DataFrame(raw_tpex_price)[["SecuritiesCompanyCode", "CompanyName", "Close", "TradingShares"]].copy()
df_tpex_p = df_tpex_p.rename(columns={
    "SecuritiesCompanyCode": "stock_id", "CompanyName": "stock_name",
    "Close": "close", "TradingShares": "vol_shares",
})
df_tpex_p["stock_id"] = df_tpex_p["stock_id"].str.strip()
df_tpex_p["market"] = "上櫃"

df_price = pd.concat([df_twse_p, df_tpex_p], ignore_index=True)
df_price["close"]     = pd.to_numeric(df_price["close"],     errors="coerce")
df_price["vol_shares"] = pd.to_numeric(df_price["vol_shares"], errors="coerce")
df_price["vol_lot"]   = df_price["vol_shares"] / 1000
df_price = df_price[["stock_id", "stock_name", "market", "close", "vol_lot"]].dropna()

# ─────────────────────────────────────────────
# Step 3：套用股價 + 成交量篩選
# ─────────────────────────────────────────────
df_price_filtered = df_price[
    (df_price["close"]   > price_min) &
    (df_price["vol_lot"] > vol_min)
].copy().reset_index(drop=True)

n_price_filtered = len(df_price_filtered)
progress.progress(35, text=f"📊 股價/成交量通過 {n_price_filtered} 檔，查詢外資買賣超...")

if n_price_filtered == 0:
    progress.progress(100, text="✅ 完成")
    st.warning("⚠️ 沒有股票通過股價/成交量條件，請放寬設定。")
    st.stop()

# ─────────────────────────────────────────────
# Step 4：用免費 TWSE/TPEX 三大法人 API 取近 N 交易日外資買賣超
# ─────────────────────────────────────────────
progress.progress(40, text=f"🏦 查詢 TWSE/TPEX 外資買賣超（近 {days_n} 交易日）...")

# 從昨天往前找最近 days_n 個有資料的交易日（跳過週末假日）
_daily_frames  = []
_valid_dates   = []
for _i in range(days_n + 15):   # 加足緩衝，防止連續假日
    _d = datetime.today().date() - timedelta(days=_i + 1)
    if _d.weekday() >= 5:          # 跳過週六日
        continue
    _date_ymd = _d.strftime("%Y%m%d")
    _date_roc = f"{_d.year - 1911}/{_d.month:02d}/{_d.day:02d}"
    _df_tw = fetch_twse_3insti(_date_ymd)
    _df_tp = fetch_tpex_3insti(_date_roc)
    if _df_tw.empty and _df_tp.empty:
        continue                    # 該日無資料（假日），跳過
    _valid_dates.append(_d)
    _daily_frames.append(pd.concat([_df_tw, _df_tp], ignore_index=True))
    if len(_valid_dates) >= days_n:
        break

if not _daily_frames:
    progress.progress(100, text="✅ 完成")
    st.error("❌ 無法取得 TWSE/TPEX 三大法人資料，請稍後再試。")
    st.stop()

_df_inst_all = pd.concat(_daily_frames, ignore_index=True)
_df_inst_sum = _df_inst_all.groupby("stock_id", as_index=False)["foreign_net_shares"].sum()
_df_inst_sum["foreign_net_buy_lot"] = _df_inst_sum["foreign_net_shares"] / 1000  # 股 → 張

_inst_date0 = _valid_dates[-1].strftime("%Y-%m-%d") if _valid_dates else "-"
_inst_date1 = _valid_dates[0].strftime("%Y-%m-%d")  if _valid_dates else "-"

_n_inst_unique = _df_inst_sum["stock_id"].nunique()
progress.progress(55, text=f"🔧 外資資料已取得（{_inst_date0} ~ {_inst_date1}，共 {len(_valid_dates)} 個交易日，{_n_inst_unique} 檔有外資異動）...")

# ─────────────────────────────────────────────
# Step 5：合併股價，套用外資買超條件
# ─────────────────────────────────────────────
df_merged = df_price_filtered.merge(_df_inst_sum[["stock_id", "foreign_net_buy_lot"]], on="stock_id", how="inner")
_n_matched = len(df_merged)   # 合併後有多少檔（debug 用）
df_candidates = df_merged[
    df_merged["foreign_net_buy_lot"] > foreign_buy_min
].copy().reset_index(drop=True)

n_candidates = len(df_candidates)
progress.progress(65, text=f"🏦 join後{_n_matched}檔有外資紀錄，買超>{foreign_buy_min:,.0f}張通過 {n_candidates} 檔，準備套用官方本益比...")

if n_candidates == 0:
    progress.progress(100, text="✅ 完成")
    # 顯示前 20 大外資買超股票，方便使用者知道實際數值
    df_top_foreign = df_merged.sort_values("foreign_net_buy_lot", ascending=False).head(20)
    st.warning(
        f"⚠️ 股價/成交量通過 {n_price_filtered} 檔，"
        f"與外資買賣超資料 join 後剩 {_n_matched} 檔，"
        f"但外資買超 > {foreign_buy_min:,.0f} 張後無符合，請放寬條件。"
    )
    if not df_top_foreign.empty:
        st.caption(f"以下為外資近{days_n}日買超最大前20檔（供參考，實際數值）：")
        st.dataframe(
            df_top_foreign[["stock_id", "stock_name", "market", "close", "foreign_net_buy_lot", "vol_lot"]]
            .rename(columns={"stock_id":"股票代碼","stock_name":"股票名稱","market":"市場",
                             "close":"收盤價(元)","foreign_net_buy_lot":"外資買超(張)","vol_lot":"成交量(張)"}),
            use_container_width=True, hide_index=True,
        )
    st.stop()

# ─────────────────────────────────────────────
# Step 7：套用官方本益比與反推近四季EPS
# ─────────────────────────────────────────────
progress.progress(78, text=f"🔍 候選股 {n_candidates} 檔，套用官方上市櫃本益比...")
df_public_pe = fetch_public_pe_ratios()
if df_public_pe.empty:
    progress.progress(100, text="✅ 完成")
    st.error("❌ 官方上市櫃本益比資料目前抓取失敗，無法套用 PE 條件，請稍後再試。")
    st.stop()
df_all = attach_public_valuation(df_candidates, df_public_pe)

# 套用本益比條件
df_result = df_all[
    df_all["pe_ratio"].notna() & (df_all["pe_ratio"] < pe_max)
].copy().reset_index(drop=True)

progress.progress(100, text="✅ 選股完成！")

# 存入 session_state，避免按下載後 rerun 時資料消失
st.session_state["chip_screener_result"] = df_result

# ─────────────────────────────────────────────
# 顯示結果
# ─────────────────────────────────────────────
count = len(df_result)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("符合條件",       f"{count} 檔")
col2.metric("外資近N日買超",  f"> {foreign_buy_min:,.0f} 張")
col3.metric("本益比",         f"< {pe_max:.0f} 倍")
col4.metric("股價",           f"> {price_min:.0f} 元")
col5.metric("當日成交量",     f"> {int(vol_min):,} 張")

st.divider()

if count == 0:
    st.warning(
        f"⚠️ 外資買超條件通過 {n_candidates} 檔，但加上本益比條件（< {pe_max:.0f} 倍）後無符合，請放寬 PE 條件。"
    )
    df_no_pe = df_all[df_all["pe_ratio"].notna()].sort_values("pe_ratio")
    if not df_no_pe.empty:
        st.caption("以下為通過外資買超條件但本益比不符的股票（供參考）：")
        st.dataframe(
            df_no_pe[["stock_id", "stock_name", "market", "close", "pe_ratio", "foreign_net_buy_lot"]].head(20),
            use_container_width=True, hide_index=True,
        )
    st.stop()

st.subheader(f"📋 外資籌碼重壓名單（共 {count} 檔，以收盤價降冪排序）")

# 顯示資料日期
try:
    _price_date_raw = raw_twse_price[0].get("Date", "")
    if len(_price_date_raw) == 7:
        _y, _m, _d = int(_price_date_raw[:3]) + 1911, _price_date_raw[3:5], _price_date_raw[5:7]
        _date_str = f"{_y}/{_m}/{_d}"
    else:
        _date_str = _price_date_raw
    st.caption(
        f"📅 股價資料日期：{_date_str}（TWSE 最近交易日）"
        f"｜外資買賣超統計：{_inst_date0} ~ {_inst_date1}（最近 {days_n} 交易日）"
    )
except Exception:
    pass

display_df = df_result.rename(columns={
    "stock_id":            "股票代碼",
    "stock_name":          "股票名稱",
    "market":              "市場",
    "close":               "收盤價(元)",
    "vol_lot":             "當日成交量(張)",
    "foreign_net_buy_lot": "外資近N日買超(張)",
    "pe_ratio":            "本益比(倍)",
    "pe_label":            "PE口徑",
})[["股票代碼", "股票名稱", "市場", "收盤價(元)", "本益比(倍)", "PE口徑",
    "外資近N日買超(張)", "當日成交量(張)"]]

display_df["收盤價(元)"]        = display_df["收盤價(元)"].round(2)
display_df["本益比(倍)"]        = display_df["本益比(倍)"].round(2)
display_df["外資近N日買超(張)"] = pd.to_numeric(display_df["外資近N日買超(張)"], errors="coerce").round(0).astype(int)
display_df["當日成交量(張)"]    = display_df["當日成交量(張)"].round(0).astype(int)
display_df = display_df.sort_values("收盤價(元)", ascending=False).reset_index(drop=True)

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "股票代碼":          st.column_config.TextColumn("股票代碼",   width="small"),
        "股票名稱":          st.column_config.TextColumn("股票名稱",   width="medium"),
        "市場":              st.column_config.TextColumn("市場",       width="small"),
        "收盤價(元)":        st.column_config.NumberColumn("收盤價(元)",        format="%.2f"),
        "本益比(倍)":        st.column_config.NumberColumn("本益比(倍)",        format="%.2f"),
        "PE口徑":            st.column_config.TextColumn("PE口徑", width="medium"),
        "外資近N日買超(張)": st.column_config.NumberColumn("外資近N日買超(張)", format="%d"),
        "當日成交量(張)":    st.column_config.NumberColumn("當日成交量(張)",    format="%d"),
    },
)

csv_bytes = dataframe_to_csv_bytes(display_df)
st.download_button(
    label="⬇️ 下載 CSV（Excel 可直接開啟）",
    data=csv_bytes,
    file_name=f"外資籌碼重壓_{datetime.today().strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

st.divider()
st.caption("📡 股價：TWSE + TPEX OpenAPI（免費）｜ 外資買賣超：TWSE + TPEX（免費）｜ 本益比：官方上市櫃 API")
st.caption("📢 本系統僅供學術研究與教育用途，不構成任何投資建議")

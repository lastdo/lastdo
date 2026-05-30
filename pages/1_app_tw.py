import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from groq import Groq
from datetime import datetime, timedelta
from dotenv import load_dotenv
from _app_common import ensure_analysis_dir, get_runtime_secret
from _export_utils import CSV_ENCODING, dataframe_to_csv_bytes

ANALYSIS_DIR = ensure_analysis_dir()

load_dotenv()  # 從 .env 自動載入環境變數

# ─────────────────────────────────────────────
# 頁面基本設定
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AI 台股趨勢分析系統",
    page_icon="📈",
    layout="wide",
)

from _style import apply_style, page_header, render_global_navigation
apply_style()
page_header("📈", "AI 台股趨勢分析系統", "技術面分析 · AI 智慧報告 · 籌碼面觀察")


# ─────────────────────────────────────────────
# F-001 側邊欄控制區
# ─────────────────────────────────────────────
with st.sidebar:
    render_global_navigation("app_tw")
    st.markdown("---")
    st.header("📊 分析設定")
    st.divider()

    _incoming = st.session_state.pop("selected_symbol", None)
    if _incoming:
        # 從庫存頁跳來，清掉上一次的分析快取，強制用新股號重新分析
        st.session_state.pop("_cache", None)
        st.session_state.pop("_ai_report", None)
        st.session_state.pop("_news_data", None)
        st.session_state["symbol_input_widget"] = _incoming
    _default_symbol = _incoming or st.query_params.get("symbol", "2330")
    symbol_input = st.text_input(
        "台股代碼",
        key="symbol_input_widget",
        help="請輸入台灣股票代碼（純數字）\n例如：2330（台積電）、2317（鴻海）、0050（元大台灣50）",
    ).strip()

    finmind_token = st.text_input(
        "FinMind Token（免費）",
        value=get_runtime_secret("FINMIND_TOKEN", ""),
        type="password",
        help="請至 https://finmindtrade.com 免費註冊取得 Token（免費額度每日限 600 次請求）",
    ).strip()

    groq_api_key = st.text_input(
        "Groq API Key（完全免費）",
        value=get_runtime_secret("GROQ_API_KEY", ""),
        type="password",
        help="請至 https://console.groq.com 免費申請 API Key（無需信用卡）",
    ).strip()

    default_start = datetime.today() - timedelta(days=90)
    default_end = datetime.today()

    start_date = st.date_input("起始日期", value=default_start)
    end_date = st.date_input("結束日期", value=default_end)

    analyze_btn = st.button("🔍 分析", use_container_width=True, type="primary")

    # F-009 免責聲明
    st.markdown("---")
    st.markdown(
        """
        ### 📢 免責聲明
        本系統僅供學術研究與教育用途，AI 提供的數據與分析結果僅供參考，
        **不構成投資建議或財務建議**。
        請使用者自行判斷投資決策，並承擔相關風險。
        本系統作者不對任何投資行為負責，亦不承擔任何損失責任。
        """
    )
    st.markdown("---")
    st.caption("📡 資料來源：FinMind（免費版，需註冊取得 Token）")
    st.caption("🤖 AI：Groq + Llama 3.3 70B（完全免費）")


# ─────────────────────────────────────────────
# FinMind API 共用設定
# ─────────────────────────────────────────────
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


def _finmind_get(
    dataset: str,
    data_id: str,
    start_date,
    end_date,
    token: str = "",
) -> pd.DataFrame:
    """FinMind REST API 通用請求函式。"""
    params: dict = {
        "dataset": dataset,
        "data_id": data_id,
        "start_date": str(start_date),
        "end_date": str(end_date),
    }
    if token:
        params["token"] = token
    try:
        resp = requests.get(FINMIND_URL, params=params, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") != 200 or not result.get("data"):
            return pd.DataFrame()
        return pd.DataFrame(result["data"])
    except Exception as e:
        st.error(f"❌ FinMind API 請求失敗：{e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# F-002 用 FinMind 取得台股歷史數據
# ─────────────────────────────────────────────
def get_taiwan_stock_data(symbol: str, start_date, end_date, token: str = ""):
    """
    使用 FinMind TaiwanStockPrice 取得台股歷史股價資料。
    回傳 (DataFrame, symbol)。
    FinMind 直接使用純數字股票代碼（2330、6547、0050），無需 .TW/.TWO 後綴。
    """
    df = _finmind_get("TaiwanStockPrice", symbol, start_date, end_date, token)

    if df.empty:
        st.error(
            f"❌ 找不到台股代碼「{symbol}」或該期間無資料。\n\n"
            f"請確認：\n"
            f"1. 代碼是否正確（例如：2330、2317、0050）\n"
            f"2. FinMind Token 是否正確（免費註冊：https://finmindtrade.com）\n"
            f"3. 所選日期範圍內是否有交易資料"
        )
        return pd.DataFrame(), symbol

    # FinMind 欄位對應：max=最高, min=最低, Trading_Volume=成交量
    df = df.rename(columns={
        "max":            "high",
        "min":            "low",
        "Trading_Volume": "volume",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df, symbol


# ─────────────────────────────────────────────
# 取得台灣加權指數（TAIEX）同期報酬率
# ─────────────────────────────────────────────
def get_taiex_return(start_date, end_date, token: str = "") -> float | None:
    """
    用 FinMind TaiwanStockPrice data_id='TAIEX' 取得加權指數，
    計算與個股相同分析期間的漲跌幅（%）。失敗回傳 None。
    """
    df = _finmind_get("TaiwanStockPrice", "TAIEX", start_date, end_date, token)
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 2:
        return None
    start_close = float(df["close"].iloc[0])
    end_close   = float(df["close"].iloc[-1])
    if start_close == 0:
        return None
    return (end_close - start_close) / start_close * 100


# ─────────────────────────────────────────────
# 嘗試取得股票中文名稱
# ─────────────────────────────────────────────
def get_stock_name(symbol: str, token: str = "") -> str:
    """從 FinMind TaiwanStockInfo 取得股票中文名稱，失敗則回傳代碼。"""
    try:
        params: dict = {"dataset": "TaiwanStockInfo"}
        if token:
            params["token"] = token
        resp = requests.get(FINMIND_URL, params=params, timeout=15)
        result = resp.json()
        if result.get("status") == 200 and result.get("data"):
            info_df = pd.DataFrame(result["data"])
            row = info_df[info_df["stock_id"] == symbol]
            if not row.empty:
                return str(row.iloc[0].get("stock_name", symbol))
    except Exception:
        pass
    return symbol


# ─────────────────────────────────────────────
# F-003 依日期範圍過濾資料
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# 三大法人買賣超資料
# ─────────────────────────────────────────────
def get_institutional_investors(
    symbol: str,
    start_date,
    end_date,
    token: str = "",
) -> pd.DataFrame:
    """
    取得三大法人買賣超資料（外資及陸資、投信、自營商）。
    回傳 pivot DataFrame，欄位：date, 外資買賣超, 投信買賣超, 自營商買賣超
    及對應累積欄位（外資累積, 投信累積, 自營商累積）。
    單位：張（FinMind 原始為股，已 ÷ 1000 換算）。
    """
    df = _finmind_get(
        "TaiwanStockInstitutionalInvestorsBuySell", symbol, start_date, end_date, token
    )
    if df.empty:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0)
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0)
    df["net"] = df["buy"] - df["sell"]

    # FinMind 英文類別對應三大法人
    # Foreign_Investor / Foreign_Dealer_Self → 外資
    # Investment_Trust                        → 投信
    # Dealer_self / Dealer_Hedging            → 自營商
    category_map = {
        "Foreign_Investor":   "外資",
        "Foreign_Dealer_Self":"外資",
        "Investment_Trust":   "投信",
        "Dealer_self":        "自營商",
        "Dealer_Hedging":     "自營商",
    }
    df = df[df["name"].isin(category_map)].copy()
    df["group"] = df["name"].map(category_map)

    pivot = (
        df.pivot_table(index="date", columns="group", values="net", aggfunc="sum")
        .reset_index()
    )
    pivot = pivot.rename(columns={
        "外資":   "外資買賣超",
        "投信":   "投信買賣超",
        "自營商": "自營商買賣超",
    })
    for col in ["外資買賣超", "投信買賣超", "自營商買賣超"]:
        if col not in pivot.columns:
            pivot[col] = 0
        pivot[col] = (pivot[col].fillna(0) / 1000).round(0)  # 股 → 張

    pivot = pivot.sort_values("date").reset_index(drop=True)
    pivot["外資累積"] = pivot["外資買賣超"].cumsum()
    pivot["投信累積"] = pivot["投信買賣超"].cumsum()
    pivot["自營商累積"] = pivot["自營商買賣超"].cumsum()
    return pivot


# ─────────────────────────────────────────────
# 月營收資料（近兩年）
# ─────────────────────────────────────────────
def get_monthly_revenue(symbol: str, token: str = "") -> pd.DataFrame:
    """
    取得近兩年月營收資料（TaiwanStockMonthRevenue）。
    回傳欄位：date(年月), revenue(千元), yoy(年增率%)。
    """
    two_years_ago = (datetime.today() - timedelta(days=730)).strftime("%Y-%m-%d")
    today_str = datetime.today().strftime("%Y-%m-%d")
    df = _finmind_get("TaiwanStockMonthRevenue", symbol, two_years_ago, today_str, token)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    # FinMind 月營收日期為「公告日」（當月初），實際營收月為前一個月
    # 例如：2026-03-01 公告的是 2026 年 2 月營收，需往前移一個月
    df["date"] = df["date"] - pd.DateOffset(months=1)
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()  # 統一為月初
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    # 依實際日期比對同月去年營收，避免資料有缺漏時 pct_change(12) 算錯月份
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month
    rev_ly = df[["year", "month", "revenue"]].copy()
    rev_ly["year"] = rev_ly["year"] + 1
    rev_ly = rev_ly.rename(columns={"revenue": "revenue_ly"})
    df = df.merge(rev_ly, on=["year", "month"], how="left")
    df["yoy"] = (df["revenue"] / df["revenue_ly"] - 1) * 100
    return df[["date", "revenue", "yoy"]]


# ─────────────────────────────────────────────
# 季/年 EPS 資料（近兩年）
# ─────────────────────────────────────────────
def get_eps_data(symbol: str, token: str = "") -> tuple:
    """
    取得近兩年季EPS與年EPS（TaiwanStockFinancialStatements）。
    回傳 (quarterly_df, annual_df)，欄位：date, eps。
    """
    # 從兩年前的1月1日開始，確保 Q1 也包含在內，年EPS加總才完整
    start_year = datetime.today().year - 2
    start_date = f"{start_year}-01-01"
    today_str = datetime.today().strftime("%Y-%m-%d")
    df = _finmind_get("TaiwanStockFinancialStatements", symbol, start_date, today_str, token)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 篩選 EPS 項目
    eps_df = df[df["type"] == "EPS"].copy()
    if eps_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    eps_df["date"] = pd.to_datetime(eps_df["date"])
    eps_df["eps"] = pd.to_numeric(eps_df["value"], errors="coerce")
    eps_df = eps_df.sort_values("date").reset_index(drop=True)

    # 季EPS：取最近 8 季
    quarterly = eps_df[["date", "eps"]].tail(8).copy()

    # 年EPS：以日曆年度加總（有完整 Q1~Q4 才正確）
    annual = eps_df.copy()
    annual["year"] = annual["date"].dt.year
    annual_agg = annual.groupby("year")["eps"].sum().reset_index()
    annual_agg["date"] = pd.to_datetime(annual_agg["year"].astype(str) + "-12-31")
    annual_df = annual_agg[["date", "eps"]].copy()

    return quarterly, annual_df


# ─────────────────────────────────────────────
# 季毛利率資料（近兩年，來自財務報表）
# ─────────────────────────────────────────────
def get_gross_margin(symbol: str, token: str = "") -> pd.DataFrame:
    """
    取得近兩年季毛利率（TaiwanStockFinancialStatements）。
    回傳欄位：date, gross_profit, revenue, gross_margin(%)。
    """
    two_years_ago = (datetime.today() - timedelta(days=730)).strftime("%Y-%m-%d")
    today_str = datetime.today().strftime("%Y-%m-%d")
    df = _finmind_get("TaiwanStockFinancialStatements", symbol, two_years_ago, today_str, token)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    pivot = df[df["type"].isin(["GrossProfit", "Revenue"])].pivot_table(
        index="date", columns="type", values="value", aggfunc="sum"
    ).reset_index()
    if "GrossProfit" not in pivot.columns or "Revenue" not in pivot.columns:
        return pd.DataFrame()
    pivot = pivot[pivot["Revenue"] > 0].copy()
    pivot["gross_margin"] = (pivot["GrossProfit"] / pivot["Revenue"] * 100).round(2)
    pivot = pivot.sort_values("date").reset_index(drop=True)
    pivot.columns.name = None
    return pivot[["date", "GrossProfit", "Revenue", "gross_margin"]].rename(
        columns={"GrossProfit": "gross_profit", "Revenue": "revenue"}
    )


# ─────────────────────────────────────────────
# 外資持股比例資料（近三個月）
# ─────────────────────────────────────────────
def get_foreign_holding(symbol: str, token: str = "") -> pd.DataFrame:
    """
    取得近三個月外資持股比例（TaiwanStockShareholding）。
    回傳欄位：date, foreign_hold_ratio(%)。
    """
    three_months_ago = (datetime.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    today_str = datetime.today().strftime("%Y-%m-%d")
    df = _finmind_get("TaiwanStockShareholding", symbol, three_months_ago, today_str, token)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    # FinMind TaiwanStockShareholding 欄位說明：
    #   ForeignInvestmentSharesRatio = 外資實際持股比例（正確欄位）
    #   ForeignInvestmentRemainRatio = 外資剩餘可買進比例（不是持股比例，勿誤用）
    if "ForeignInvestmentSharesRatio" not in df.columns:
        return pd.DataFrame()
    df["foreign_hold_ratio"] = pd.to_numeric(df["ForeignInvestmentSharesRatio"], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "foreign_hold_ratio"]]


# ─────────────────────────────────────────────
# F-003 計算移動平均線
# ─────────────────────────────────────────────
def get_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """計算 MA5、MA10、MA20、MA60 移動平均線。"""
    df = df.copy()
    for window in [5, 10, 20, 60]:
        df[f"MA{window}"] = df["close"].rolling(window=window, min_periods=1).mean()
    return df


# ─────────────────────────────────────────────
# 技術指標計算（RSI / MACD / KD）
# ─────────────────────────────────────────────
def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).clip(0, 100)


def calculate_macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    sig = dif.ewm(span=signal, adjust=False).mean()
    hist = dif - sig
    return dif, sig, hist


def calculate_kd(df: pd.DataFrame, k_period: int = 9, smooth: int = 3) -> tuple:
    low_min = df["low"].rolling(window=k_period, min_periods=1).min()
    high_max = df["high"].rolling(window=k_period, min_periods=1).max()
    denom = high_max - low_min
    rsv = ((df["close"] - low_min) / denom.where(denom != 0, 1)) * 100
    k = rsv.ewm(alpha=1 / smooth, adjust=False).mean()
    d = k.ewm(alpha=1 / smooth, adjust=False).mean()
    return k, d


# ─────────────────────────────────────────────
# 抓取 Google News RSS 近一年新聞
# ─────────────────────────────────────────────
def get_stock_news(symbol: str, stock_name: str, max_items: int = 15) -> list:
    """
    透過 Google News RSS 抓取與個股相關的近一年新聞標題與日期。
    不需要任何 API Key，完全免費。
    回傳 list of dict: [{date, title}, ...]
    """
    import xml.etree.ElementTree as ET
    from urllib.parse import quote
    from email.utils import parsedate_to_datetime

    one_year_ago = datetime.today() - timedelta(days=365)
    query = quote(f"{stock_name} {symbol}")
    url = (
        f"https://news.google.com/rss/search"
        f"?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )
    news_list = []
    try:
        resp = requests.get(
            url, timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; StockNewsBot/1.0)"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title_el = item.find("title")
            pub_date_el = item.find("pubDate")
            if title_el is None:
                continue
            title = (title_el.text or "").strip()
            pub_date_str = pub_date_el.text if pub_date_el is not None else ""
            try:
                pub_dt = parsedate_to_datetime(pub_date_str).replace(tzinfo=None)
                if pub_dt < one_year_ago:
                    continue
                date_str = pub_dt.strftime("%Y-%m-%d")
            except Exception:
                date_str = pub_date_str
            news_list.append({"date": date_str, "title": title})
            if len(news_list) >= max_items:
                break
    except Exception:
        pass
    return news_list


# ─────────────────────────────────────────────
# F-006 呼叫 Groq 進行技術分析（完全免費）
# ─────────────────────────────────────────────
def generate_ai_insights(
    full_symbol: str,
    stock_name: str,
    stock_data: pd.DataFrame,
    ii_data: pd.DataFrame,
    groq_api_key: str,
    rev_data: pd.DataFrame = None,
    eps_q: pd.DataFrame = None,
    eps_y: pd.DataFrame = None,
    gross_margin_data: pd.DataFrame = None,
    foreign_holding_data: pd.DataFrame = None,
    news_data: list = None,
    taiex_change: float | None = None,
) -> str:
    """使用 Groq + Llama 3.3 70B（完全免費）對台股歷史數據進行深度技術分析。"""

    first_date   = stock_data["date"].iloc[0].strftime("%Y-%m-%d")
    last_date    = stock_data["date"].iloc[-1].strftime("%Y-%m-%d")
    start_price  = float(stock_data["close"].iloc[0])
    end_price    = float(stock_data["close"].iloc[-1])
    price_change = (end_price - start_price) / start_price * 100

    # ── 大盤報酬率與 Alpha（Python 預先計算，直接提供給 AI）──
    if taiex_change is not None:
        alpha = price_change - taiex_change
        taiex_str = f"{taiex_change:+.2f}%"
        alpha_str = f"{alpha:+.2f}%（{'跑贏大盤' if alpha > 0.5 else '跑輸大盤' if alpha < -0.5 else '與大盤相當'}）"
    else:
        taiex_str = "無法取得（FinMind TAIEX 資料不足）"
        alpha_str = "無法計算"

    # 準備送給 AI 的精簡版資料（最多 60 筆，避免超出 token 限制）
    # volume 換算為張（÷1000），讓 AI 直接拿到正確單位
    cols = ["date", "open", "high", "low", "close", "volume",
            "MA5", "MA10", "MA20", "MA60"]
    sample_df = stock_data[cols].tail(60).copy()
    sample_df["date"] = sample_df["date"].dt.strftime("%Y-%m-%d")
    sample_df["volume"] = (sample_df["volume"] / 1000).round(0).astype(int)
    data_json = sample_df.to_json(orient="records", force_ascii=False)

    # ── 計算真實本益比（去年EPS + 推估全年EPS）──
    _MONTH_TO_Q = {3: 1, 6: 2, 9: 3, 12: 4}
    pe_section = ""
    if eps_q is not None and not eps_q.empty:
        q = eps_q.copy()
        q["year"] = q["date"].dt.year
        q["month"] = q["date"].dt.month
        latest_year = int(q["year"].max())
        latest_year_q = q[q["year"] == latest_year].sort_values("date")
        num_q_latest = len(latest_year_q)
        prev_year = latest_year - 1
        prev_year_q = q[q["year"] == prev_year].sort_values("date")

        # ── 去年EPS（前一完整年度加總）──
        if not prev_year_q.empty:
            last_year_eps = float(prev_year_q["eps"].sum())
            last_year_labels = [
                f"{prev_year}Q{_MONTH_TO_Q.get(int(r['date'].month), '?')}({r['eps']:.2f})"
                for _, r in prev_year_q.iterrows()
            ]
            last_year_note = " + ".join(last_year_labels) + f" = {last_year_eps:.2f}"
            last_year_section = (
                f"- **【提供數據】去年EPS（{prev_year}年）**：NT${last_year_eps:.2f} 元\n"
                f"  計算方式：{last_year_note}\n"
            )
        else:
            last_year_section = ""

        # ── 推估全年EPS（今年已有各季 + 去年剩餘各季）──
        latest_months = set(latest_year_q["month"].tolist())
        remaining_prev = prev_year_q[~prev_year_q["month"].isin(latest_months)]
        fw_parts = []
        forward_eps = 0.0
        for _, r in latest_year_q.iterrows():
            qn = _MONTH_TO_Q.get(int(r["date"].month), "?")
            fw_parts.append(f"{latest_year}Q{qn}({r['eps']:.2f})")
            forward_eps += float(r["eps"])
        for _, r in remaining_prev.iterrows():
            qn = _MONTH_TO_Q.get(int(r["date"].month), "?")
            fw_parts.append(f"{prev_year}Q{qn}({r['eps']:.2f})")
            forward_eps += float(r["eps"])
        fw_note = " + ".join(fw_parts) + f" = {forward_eps:.2f}"
        if num_q_latest >= 4:
            fw_label = f"{latest_year}年全年（已完整）"
        else:
            cur_part = f"{latest_year}Q1" if num_q_latest == 1 else f"{latest_year}Q1-Q{num_q_latest}"
            rem_start = num_q_latest + 1
            prev_part = f"{prev_year}Q{rem_start}" if rem_start == 4 else f"{prev_year}Q{rem_start}-Q4"
            fw_label = f"{cur_part}+{prev_part}"

        if forward_eps > 0:
            pe_ratio = end_price / forward_eps
            pe_section = (
                last_year_section +
                f"- **【提供數據】推估全年EPS（{fw_label}）**：NT${forward_eps:.2f} 元\n"
                f"  計算方式：{fw_note}\n"
                f"- **【提供數據】本益比（股價/推估全年EPS）**：{end_price:.2f} / {forward_eps:.2f} = **{pe_ratio:.1f} 倍**\n"
            )
        else:
            pe_section = (
                last_year_section +
                f"- **【提供數據】推估全年EPS（{fw_label}）**：NT${forward_eps:.2f} 元（虧損或負值，本益比無意義）\n"
                f"  計算方式：{fw_note}\n"
            )
    elif eps_y is not None and not eps_y.empty:
        latest_annual_eps = float(eps_y.sort_values("date").iloc[-1]["eps"])
        if latest_annual_eps > 0:
            pe_ratio = end_price / latest_annual_eps
            pe_section = (
                f"- **【提供數據】年EPS（最新年度加總）**：NT${latest_annual_eps:.2f} 元\n"
                f"- **【提供數據】本益比（股價/年EPS）**：{end_price:.2f} / {latest_annual_eps:.2f} = **{pe_ratio:.1f} 倍**\n"
            )
        else:
            pe_section = f"- **【提供數據】年EPS（最新年度）**：NT${latest_annual_eps:.2f} 元（虧損，本益比無意義）\n"
    else:
        pe_section = "- 本益比：FinMind EPS資料不足，請依公開資訊補充\n"

    # ── 整理真實月營收年增率 ──
    rev_section = ""
    if rev_data is not None and not rev_data.empty:
        rev_display = rev_data.dropna(subset=["yoy"]).tail(6).copy()
        if not rev_display.empty:
            rev_display["date"] = rev_display["date"].dt.strftime("%Y-%m")
            rev_lines = [f"  {r['date']}：單月營收年增率 {r['yoy']:+.1f}%（月營收 {r['revenue']:,.0f} 千元）" for _, r in rev_display.iterrows()]
            rev_section = "- **【提供數據】近6個月單月營收年增率（實際數據，每月與去年同月相比）**：\n" + "\n".join(rev_lines) + "\n"
        else:
            rev_section = "- 月營收年增率：資料不足（需至少一年歷史資料才能計算年增率）\n"
    else:
        rev_section = "- 月營收：FinMind資料不足，請依公開資訊補充\n"

    # ── 整理真實季毛利率 ──
    gm_section = ""
    if gross_margin_data is not None and not gross_margin_data.empty:
        gm_rows = gross_margin_data.tail(8).copy()
        gm_rows["date"] = gm_rows["date"].dt.strftime("%Y-%m")
        gm_lines = [
            f"  {r['date']}：毛利率 {r['gross_margin']:.1f}%"
            f"（毛利 {r['gross_profit']:,.0f} / 營收 {r['revenue']:,.0f} 千元）"
            for _, r in gm_rows.iterrows()
        ]
        gm_section = "- **【提供數據】近期季毛利率（實際數據，禁止另行估計）**：\n" + "\n".join(gm_lines) + "\n"
    else:
        gm_section = "- **毛利率**：【無資料】FinMind 財務報表資料不足，禁止估計任何數字，請直接標注「無資料」\n"

    # ── 整理真實外資持股比例 ──
    fh_section = ""
    if foreign_holding_data is not None and not foreign_holding_data.empty:
        fh_rows = foreign_holding_data.tail(6).copy()
        fh_rows["date"] = fh_rows["date"].dt.strftime("%Y-%m-%d")
        fh_lines = [f"  {r['date']}：外資持股比例 {r['foreign_hold_ratio']:.2f}%" for _, r in fh_rows.iterrows()]
        fh_section = "- **【提供數據】外資單獨持股比例（不含投信、自營商，實際數據，禁止另行估計）**：\n" + "\n".join(fh_lines) + "\n"
    else:
        fh_section = "- **外資單獨持股比例**：【無資料】FinMind 持股資料不足，禁止猜測任何百分比，請直接標注「無資料」\n"

    # ── 整理外部抓取新聞 ──
    if news_data:
        news_lines = [f"  {n['date']}：{n['title']}" for n in news_data]
        news_section = (
            f"### 【即時抓取新聞】近一年 {stock_name}（{full_symbol}）相關新聞（共 {len(news_data)} 則，來源：Google News）\n"
            + "\n".join(news_lines) + "\n"
        )
    else:
        news_section = f"### 近一年新聞：抓取失敗（網路或 Google News 無結果），請依訓練資料補充\n"

    # 準備三大法人資料摘要
    total_foreign = 0
    total_trust   = 0
    total_dealer  = 0
    last5_foreign = 0
    last5_trust   = 0
    last5_dealer  = 0
    last5_section = "- **【提供數據】近5日三大法人買賣超**：資料不足（少於5筆）\n"
    if not ii_data.empty:
        ii_sample = ii_data[["date", "外資買賣超", "投信買賣超", "自營商買賣超"]].tail(30).copy()
        ii_sample["date"] = ii_sample["date"].dt.strftime("%Y-%m-%d")
        ii_json = ii_sample.to_json(orient="records", force_ascii=False)
        total_foreign = int(ii_data["外資買賣超"].sum())
        total_trust   = int(ii_data["投信買賣超"].sum())
        total_dealer  = int(ii_data["自營商買賣超"].sum())
        # 近5日各法人合計（Python預先計算，不依賴AI解析JSON）
        ii_last5 = ii_data.tail(5)
        last5_foreign = int(ii_last5["外資買賣超"].sum())
        last5_trust   = int(ii_last5["投信買賣超"].sum())
        last5_dealer  = int(ii_last5["自營商買賣超"].sum())
        last5_section = (
            f"- **【提供數據】近5日三大法人買賣超合計（已預先計算，共{len(ii_last5)}個交易日）**：\n"
            f"  - 外資近5日合計：{last5_foreign:+,} 張（{'買超' if last5_foreign >= 0 else '賣超'}）\n"
            f"  - 投信近5日合計：{last5_trust:+,} 張（{'買超' if last5_trust >= 0 else '賣超'}）\n"
            f"  - 自營商近5日合計：{last5_dealer:+,} 張（{'買超' if last5_dealer >= 0 else '賣超'}）\n"
        )
        ii_section = f"""
### 【提供數據】三大法人買賣超（近30日，單位：張）
{ii_json}
"""
    else:
        ii_section = "\n### 三大法人資料：本次無法取得（禁止估計任何數字）\n"

    prompt = f"""請對 {full_symbol}（{stock_name}）進行深度台股研究報告，分析品質要達到券商研究員水準。

## 基礎數據（來自 FinMind API）
- 分析期間：{first_date} 至 {last_date}
- 期間價格變化：{price_change:.2f}%（從 NT${start_price:.2f} → NT${end_price:.2f}）
- 最新收盤價：NT${end_price:.2f}

### 【提供數據】股價與技術指標（最近60筆交易日，JSON格式）
※ volume 欄位單位為「張」，價格單位為新台幣元
{data_json}
{ii_section}
{news_section}
---

## 分析要求（每節都必須給出具體數字，不可只說定性描述）

### 1. 趨勢分析
請明確說明：
- **整月趨勢**：從數據中計算出本月漲跌幅、高低點區間（說明具體元數）
- **近五日趨勢**：近五交易日的走向與量能變化（volume 欄位單位為張，請正確判斷量能增減方向，數字大=量大、數字小=量縮）
- **關鍵支撐**：從MA線或歷史K棒識別出具體支撐價位（x元）
- **關鍵阻力**：明確說明阻力價位（x元）
- 趨勢強弱判斷（多頭排列／死亡交叉等，用MA數據驗證）

### 2. 基本面分析
{pe_section}{gm_section}{rev_section}  → 根據以上實際月增率數字，分析趨勢方向（加速成長/趨緩/衰退）及可能原因

- **法人目標價（優先從上方【即時抓取新聞】尋找，再補充訓練知識）**：先掃描上方即時新聞標題，若有包含目標價、評等、買進/中立/賣出、調升/調降等關鍵字的新聞，請直接引用並標注新聞日期與機構名稱。若新聞中找不到，再從訓練知識補充具體券商報告（如摩根大通、花旗、瑞銀、野村、元大等），列出目標價數字、評等與大約時間。若兩者均無具體數字，才寫「目前新聞與訓練資料均無明確目標價，建議查閱最新研究報告」。絕對禁止捏造數字。
- **利基與利空（根據上方【即時抓取新聞】，不得使用訓練資料舊事件）**：
  - 利多（2-3項）：從上方「即時抓取新聞」清單中，挑選與公司正面發展相關的標題，格式：「[新聞日期] [還原新聞核心事件]：[推斷對股價/業績的具體正面影響]」。若新聞標題已有數字則引用，若沒有請合理推斷影響方向，禁止捏造不存在於新聞中的數字。
  - 利空（1-2項）：從即時新聞清單中優先尋找「產業/事件類」負面訊號，包括：原物料漲價（記憶體、面板、關鍵零組件成本上升）、競爭加劇（對手新品搶市）、客戶砍單、中國市場競爭壓力、關稅或貿易管制、產品召回、獲利下修、市場需求衰退等。【嚴格禁止】將以下內容列為利空：券商買賣超統計、外資進出、籌碼變化、股價漲停、成交量放大——這些屬於籌碼面，不是利空事件。【重要】若新聞標題含有「漲停、漲幅、買超、創高、增長、成長、獲利、上調、優於預期」等正面意涵關鍵字，絕對不可歸類為利空。若即時新聞中確實找不到產業/事件類負面新聞，直接寫「本次新聞未見明顯產業利空，建議持續關注原物料成本與競爭動態」，不可強行湊數。格式與利多相同。
  - 若抓到的新聞數量不足或與個股關聯度低，請誠實說明「本次抓取新聞與個股關聯度不足」，切勿以訓練知識補充舊事件。
- **產業定位（禁止說「無法提供」）**：直接列出此公司在供應鏈的角色、你訓練資料中記得的主要客戶名稱（必須是真實公司名，如 HP、Dell、Lenovo、Apple、Samsung 等）、核心競爭優勢（具體技術或規模優勢），市占率若有訓練資料中的數字即引用，若真的沒有可以說「確切市占率數字不在訓練資料中」但前面的客戶和角色描述必須具體。

### 3. 籌碼面分析
- **【提供數據】分析期間（{first_date}～{last_date}）三大法人累積買賣超**：
  - 外資：{total_foreign:+,} 張（正=買超，負=賣超）
  - 投信：{total_trust:+,} 張
  - 自營商：{total_dealer:+,} 張
{last5_section}{fh_section}- **籌碼結構判斷**：根據以上真實數據判斷籌碼集中或分散，是否有換手現象
- **法人操作與新聞面一致性**：說明近期法人買賣方向與哪些公開消息（法說會、財報、重大合約、產業政策等）相符或背離，需引用具體事件名稱與大約時間。

### 4. 基期風險評估
必須包含：
- **本益比河流圖位置**：【提供數據】推估全年EPS已提供於上方。請計算目前PE倍數，並與近三年（2023-2025）的實際PE區間比較，說明目前PE處於近三年的低/中/高檔（禁止使用更久遠的歷史平均，避免失真）。若能得知此股近三年PE區間，請引用；否則根據提供的股價與EPS數據自行推算可能合理範圍。
- **股價所在位階**：根據上方提供的股價 JSON 數據，計算近60筆交易日的最高/最低價，說明目前收盤價在此區間的幾%分位，並補充說明近一年與近兩年大約在幾%分位。
- **殖利率安全邊際**：【提供數據】推估全年EPS已提供於上方。請根據此公司近三年的實際現金股利配發記錄（需引用具體年度股利金額或配發率），估算本年度預估現金股利，計算目前股價對應的殖利率（股利÷股價×100%），並與該股近三年各年度的殖利率數字比較，判斷目前殖利率處於近三年的高／中／低檔，說明是否提供足夠的股息保護墊（通常 > 3% 視為具保護性）。若公司不配息或配發率極低，請直接說明並解釋原因（如成長型公司傾向保留盈餘）。禁止在無任何依據的情況下捏造配發率或股利數字。
- **相對強弱（Alpha 表現）**：【提供數據】分析期間（{first_date}～{last_date}）個股報酬率為 **{price_change:+.2f}%**（已計算）；台灣加權指數（TAIEX）同期報酬率為 **{taiex_str}**（已計算）；Alpha（個股超額報酬）= {alpha_str}。請根據以上數字明確判斷是跑贏、跑平或跑輸大盤，並結合本益比河流圖位階，分析是否存在高基期導致的相對弱勢風險（即本股PE明顯高於大盤平均時，下跌空間通常大於大盤）。

### 5. 技術分析
必須包含：
- **日線**：目前K線型態？站上或跌破哪些均線？
- **週線**：週線趨勢方向，週KD或週RSI大約在哪個位置？
- **月線**：月線型態，是否仍在多頭軌道？
- **RSI**：目前RSI大約幾？超買（>70）/超賣（<30）/中性？
- **MACD**：DIF和MACD的位置？柱狀體趨勢（放大/收斂）？是否有黃金交叉/死亡交叉訊號？
- **具體操作觀察點**：請綜合以下三個來源給出具體操作建議：
  1. **技術面支撐/壓力**：根據上方提供的股價與均線數據，指出具體的支撐價位（如MA20、近期低點、整數關卡等）和壓力價位（如前波高點、MA60等），需給出具體元數。
  2. **法人與分析師看法**：若有技術分析師或法人提過此股的關鍵價位（如「突破XXX元才算確認多頭」、「跌破YYY元需停損」），請引用。
  3. **操作建議**：整合以上，明確說明：(a) 積極買點在哪個價位區間及進場條件；(b) 保守買點在哪個價位及條件；(c) 停損設在哪個價位及理由；(d) 目標價第一壓力與第二壓力各在哪裡。所有價位均需給出具體元數，不可僅說「中性區間」或「視情況而定」。

---
**免責聲明**：以上分析僅供研究參考，不構成投資建議。請以最新公開資訊為準。"""

    try:
        client = Groq(api_key=groq_api_key)
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位資深台股研究分析師，分析品質必須達到券商研究員水準。\n\n"
                        "【數字禁造規則】：prompt 中沒有以「提供數據」標注的財務數字（EPS、營收金額、毛利率百分比、法人張數等），\n"
                        "不可自行捏造。但此規則僅限於財務數字，不適用於公司名稱、事件名稱、政策名稱、客戶名稱等質性資訊。\n\n"
                        "【強制使用訓練知識】：對於以下類型的內容，你必須主動從訓練知識中提取具體資訊，禁止以「無法提供」「時效有限」為由略過：\n"
                        "- 利多/利空事件：必須從 prompt 中【即時抓取新聞】清單直接引用，禁止使用訓練資料中的舊事件補充；新聞標題有數字則引用，無數字則合理推斷影響方向\n"
                        "- 主要客戶：必須列出已知的具體客戶公司名稱（如 HP、Dell、Apple 等），不可只說「各大品牌廠商」\n"
                        "- 法人目標價：必須列出記得的具體券商名稱與目標價，不可只說「建議查閱報告」\n"
                        "- 殖利率安全邊際：必須引用具體年度股利金額，計算殖利率並與近三年區間比較，禁止捏造股利數字\n"
                        "- 相對強弱（Alpha）：個股報酬率、TAIEX報酬率與Alpha均已在prompt中以【提供數據】預先計算，直接引用即可，禁止重新估計或說「無法確認」\n"
                        "- 政策影響：必須引用具體政策名稱（如：美國晶片法案、IRA補貼）\n"
                        "若真的完全不知道特定內容，才可寫「資料不足」，但這應該是例外而非常態。\n\n"
                        "【禁止標注資料來源】：報告輸出中，嚴格禁止出現任何說明資訊來源的字眼，包括但不限於：「根據訓練資料」、「根據新聞」、「訓練資料中」、「訓練知識」、「(訓練資料，時效有限)」、「即時抓取新聞」、「本次抓取新聞」、「根據訓練知識」、「根據本次新聞」等。所有資訊一律以分析師語氣直接陳述，不得說明是從哪個來源取得的。\n"
                        "技術面指標（RSI、MACD數值）：只根據 prompt 提供的股價數據推算，不可憑空給數值。\n"
                        "使用繁體中文，格式清晰，關鍵數字加粗，所有分析僅供研究參考，非投資建議。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            model="llama-3.3-70b-versatile",
            max_tokens=8192,
            temperature=0.4,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        error_msg = str(e)
        st.error(f"❌ AI 分析失敗：{error_msg}")
        if "401" in error_msg or "invalid_api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            st.info("💡 API Key 無效。免費申請：https://console.groq.com → 登入 → API Keys → Create API Key")
        elif "429" in error_msg or "rate_limit" in error_msg.lower():
            st.info("💡 請求頻率過高，請等1分鐘後再試。Groq 免費版每分鐘最多 6,000 tokens。")
        return ""



# ─────────────────────────────────────────────
# 主程式邏輯
# ─────────────────────────────────────────────
if analyze_btn:

    # ── F-008 輸入驗證 ──────────────────────────
    if not symbol_input:
        st.error("❌ 請輸入台股代碼（例如：2330、2317、0050）。")
        st.stop()
    if not symbol_input.isdigit():
        st.error("❌ 台股代碼應為純數字，例如：2330（台積電）、0050（元大台灣50）。")
        st.stop()
    if not groq_api_key:
        st.error(
            "❌ 請輸入 Groq API Key。\n\n"
            "免費申請步驟（無需信用卡）：\n"
            "1. 前往 https://console.groq.com\n"
            "2. 登入或註冊帳號\n"
            "3. 點選「API Keys」→「Create API Key」"
        )
        st.stop()
    if start_date >= end_date:
        st.error("❌ 起始日期必須早於結束日期，請重新選擇。")
        st.stop()

    # ── F-002 獲取台股數據（FinMind） ─────────────
    with st.spinner(f"正在從 FinMind 取得 {symbol_input} 的歷史股價資料..."):
        raw_df, full_symbol = get_taiwan_stock_data(symbol_input, start_date, end_date, finmind_token)

    if raw_df.empty:
        st.stop()

    # 嘗試取得股票名稱
    with st.spinner("正在取得股票基本資訊..."):
        stock_name = get_stock_name(symbol_input, finmind_token)

    # ── F-003 計算 MA ────────────────────────────
    st.info("📊 正在計算技術指標（MA5、MA10、MA20、MA60）...")

    if len(raw_df) == 0:
        st.warning("⚠️ 所選日期範圍內沒有交易數據，請調整日期範圍後重試。")
        st.stop()

    if len(raw_df) > 500:
        st.warning("⚠️ 資料量較大（超過 500 筆），圖表載入可能稍慢，請耐心等候。")

    stock_data = get_moving_averages(raw_df)
    stock_data["RSI"] = calculate_rsi(stock_data["close"])
    dif_s, sig_s, hist_s = calculate_macd(stock_data["close"])
    stock_data["DIF"] = dif_s
    stock_data["Signal"] = sig_s
    stock_data["MACD_hist"] = hist_s
    stock_data["K"], stock_data["D"] = calculate_kd(stock_data)
    st.success(f"✅ 成功獲取 {symbol_input}（{stock_name}）共 {len(stock_data)} 筆交易資料")

    # ── 三大法人買賣超資料 ──────────────────────────
    with st.spinner("正在從 FinMind 取得三大法人買賣超資料..."):
        ii_data = get_institutional_investors(symbol_input, start_date, end_date, finmind_token)

    # ── 月營收 / EPS 資料 ────────────────────────
    with st.spinner("正在從 FinMind 取得月營收與EPS資料..."):
        rev_data = get_monthly_revenue(symbol_input, finmind_token)
        eps_q, eps_y = get_eps_data(symbol_input, finmind_token)

    with st.spinner("正在從 FinMind 取得毛利率與外資持股資料..."):
        gross_margin_data = get_gross_margin(symbol_input, finmind_token)
        foreign_holding_data = get_foreign_holding(symbol_input, finmind_token)

    # ── 台灣加權指數同期報酬率 ───────────────────────
    with st.spinner("正在取得台灣加權指數（TAIEX）同期報酬率..."):
        taiex_change = get_taiex_return(start_date, end_date, finmind_token)

    # ── 快取所有資料到 session_state（讓下載按鈕重整不會清空畫面）──
    st.session_state["_cache"] = {
        "stock_data": stock_data, "ii_data": ii_data,
        "rev_data": rev_data, "eps_q": eps_q, "eps_y": eps_y,
        "gross_margin_data": gross_margin_data,
        "foreign_holding_data": foreign_holding_data,
        "stock_name": stock_name, "full_symbol": full_symbol,
        "symbol_input": symbol_input,
        "start_date": start_date, "end_date": end_date,
        "groq_api_key": groq_api_key,
        "taiex_change": taiex_change,
    }
    st.session_state.pop("_ai_report", None)
    st.session_state.pop("_news_data", None)

# ════════════════════════════════════════════
# 渲染結果（從 session_state 讀取，不受下載按鈕重整影響）
# ════════════════════════════════════════════
if "_cache" in st.session_state:
    _c = st.session_state["_cache"]
    stock_data           = _c["stock_data"]
    ii_data              = _c["ii_data"]
    rev_data             = _c["rev_data"]
    eps_q                = _c["eps_q"]
    eps_y                = _c["eps_y"]
    gross_margin_data    = _c["gross_margin_data"]
    foreign_holding_data = _c["foreign_holding_data"]
    stock_name           = _c["stock_name"]
    full_symbol          = _c["full_symbol"]
    symbol_input         = _c["symbol_input"]
    start_date           = _c["start_date"]
    end_date             = _c["end_date"]
    groq_api_key         = _c["groq_api_key"]
    taiex_change         = _c.get("taiex_change", None)

    tab1, tab2 = st.tabs(["📊 技術面總覽", "🤖 AI 綜合分析"])

    # ────────────────────────────────────────────
    # TAB 1：技術面總覽
    # ────────────────────────────────────────────
    with tab1:

        # ── F-004 K 線圖與技術指標 ───────────────────
        st.subheader(f"📊 {symbol_input} {stock_name} 股價K線圖與技術指標")
        st.caption(f"分析期間：{start_date} ～ {end_date}　｜　資料來源：FinMind（免費版）")

        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.75, 0.25],
            vertical_spacing=0.03,
        )

        # K 線圖
        fig.add_trace(
            go.Candlestick(
                x=stock_data["date"],
                open=stock_data["open"],
                high=stock_data["high"],
                low=stock_data["low"],
                close=stock_data["close"],
                name="K線",
                increasing_line_color="#EF5350",   # 台股習慣：漲紅
                decreasing_line_color="#26A69A",   # 跌綠
            ),
            row=1, col=1,
        )

        # 移動平均線
        ma_colors = {
            "MA5":  "#FF9800",
            "MA10": "#2196F3",
            "MA20": "#9C27B0",
            "MA60": "#F44336",
        }
        for ma, color in ma_colors.items():
            fig.add_trace(
                go.Scatter(
                    x=stock_data["date"],
                    y=stock_data[ma],
                    mode="lines",
                    name=ma,
                    line=dict(color=color, width=1.5),
                ),
                row=1, col=1,
            )

        # 成交量長條圖（漲紅跌綠）
        vol_colors = [
            "#EF5350" if c >= o else "#26A69A"
            for c, o in zip(stock_data["close"], stock_data["open"])
        ]
        fig.add_trace(
            go.Bar(
                x=stock_data["date"],
                y=stock_data["volume"] / 1000,
                name="成交量(張)",
                marker_color=vol_colors,
                opacity=0.85,
            ),
            row=2, col=1,
        )

        fig.update_layout(
            title=f"{symbol_input} {stock_name} 股價走勢圖（{start_date} ～ {end_date}）",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            template="plotly_dark",
            height=650,
        )
        fig.update_xaxes(rangeslider_visible=False)
        fig.update_yaxes(title_text="價格（NT$）", row=1, col=1)
        fig.update_yaxes(title_text="成交量（張）", row=2, col=1)
        fig.update_xaxes(title_text="日期", row=2, col=1)
        st.plotly_chart(fig, use_container_width=True)

        # ── RSI / MACD / KD 技術指標圖 ──────────────────
        st.subheader("📉 技術指標（RSI / MACD / KD）")
        fig_ta = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            row_heights=[0.33, 0.34, 0.33],
            vertical_spacing=0.06,
            subplot_titles=("RSI(14)", "MACD(12,26,9)", "KD(9,3,3)"),
        )

        # RSI
        fig_ta.add_trace(
            go.Scatter(
                x=stock_data["date"], y=stock_data["RSI"].round(2),
                mode="lines", name="RSI(14)",
                line=dict(color="#FF9800", width=1.5),
            ), row=1, col=1,
        )
        fig_ta.add_hline(y=70, line_dash="dash", line_color="#EF5350", line_width=1, row=1, col=1)
        fig_ta.add_hline(y=30, line_dash="dash", line_color="#26A69A", line_width=1, row=1, col=1)

        # MACD
        macd_bar_colors = ["#EF5350" if v >= 0 else "#26A69A" for v in stock_data["MACD_hist"]]
        fig_ta.add_trace(
            go.Bar(
                x=stock_data["date"], y=stock_data["MACD_hist"].round(4),
                name="MACD柱", marker_color=macd_bar_colors, opacity=0.7,
            ), row=2, col=1,
        )
        fig_ta.add_trace(
            go.Scatter(
                x=stock_data["date"], y=stock_data["DIF"].round(4),
                mode="lines", name="DIF",
                line=dict(color="#2196F3", width=1.5),
            ), row=2, col=1,
        )
        fig_ta.add_trace(
            go.Scatter(
                x=stock_data["date"], y=stock_data["Signal"].round(4),
                mode="lines", name="Signal",
                line=dict(color="#FF9800", width=1.5),
            ), row=2, col=1,
        )

        # KD
        fig_ta.add_trace(
            go.Scatter(
                x=stock_data["date"], y=stock_data["K"].round(2),
                mode="lines", name="%K",
                line=dict(color="#E040FB", width=1.5),
            ), row=3, col=1,
        )
        fig_ta.add_trace(
            go.Scatter(
                x=stock_data["date"], y=stock_data["D"].round(2),
                mode="lines", name="%D",
                line=dict(color="#40C4FF", width=1.5),
            ), row=3, col=1,
        )
        fig_ta.add_hline(y=80, line_dash="dash", line_color="#EF5350", line_width=1, row=3, col=1)
        fig_ta.add_hline(y=20, line_dash="dash", line_color="#26A69A", line_width=1, row=3, col=1)

        fig_ta.update_layout(
            template="plotly_dark",
            height=600,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_ta.update_yaxes(title_text="RSI", row=1, col=1)
        fig_ta.update_yaxes(title_text="MACD", row=2, col=1)
        fig_ta.update_yaxes(title_text="KD", row=3, col=1)
        fig_ta.update_xaxes(title_text="日期", row=3, col=1)
        st.plotly_chart(fig_ta, use_container_width=True)

        # ── 三大法人買賣超圖 ───────────────────────────
        st.subheader("🏦 三大法人買賣超")
        if not ii_data.empty:
            # 每日買賣超長條圖（各法人獨立子圖，解決外資刻度壓縮投信/自營商問題）
            fig_ii = make_subplots(
                rows=3, cols=1,
                shared_xaxes=True,
                subplot_titles=("外資買賣超（張）", "投信買賣超（張）", "自營商買賣超（張）"),
                vertical_spacing=0.08,
                row_heights=[0.5, 0.25, 0.25],
            )
            ii_cfg = [
                ("外資買賣超", "#2196F3", 1),
                ("投信買賣超", "#4CAF50", 2),
                ("自營商買賣超", "#FF9800", 3),
            ]
            for col_name, ii_color, row_idx in ii_cfg:
                if col_name in ii_data.columns:
                    label = col_name.replace("買賣超", "")
                    # 買超（正值）：用主色，clip 讓負值顯示為 0（不出現）
                    fig_ii.add_trace(
                        go.Bar(
                            x=ii_data["date"],
                            y=ii_data[col_name].clip(lower=0),
                            name=label,
                            marker_color=ii_color,
                            opacity=0.9,
                            legendgroup=label,
                        ),
                        row=row_idx, col=1,
                    )
                    # 賣超（負值）：用灰色，clip 讓正值顯示為 0（不出現），不進圖例
                    fig_ii.add_trace(
                        go.Bar(
                            x=ii_data["date"],
                            y=ii_data[col_name].clip(upper=0),
                            name=label + "（賣超）",
                            marker_color="#888888",
                            opacity=0.85,
                            showlegend=False,
                            legendgroup=label,
                        ),
                        row=row_idx, col=1,
                    )
            fig_ii.update_layout(
                title="三大法人每日買賣超（各別獨立刻度）",
                template="plotly_dark",
                height=520,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            fig_ii.update_xaxes(title_text="日期", row=3, col=1)
            st.plotly_chart(fig_ii, use_container_width=True)

            # 累積買賣超折線圖
            fig_cum = go.Figure()
            cum_cfg = {
                "外資累積": "#2196F3",
                "投信累積": "#4CAF50",
                "自營商累積": "#FF9800",
            }
            for col, color in cum_cfg.items():
                if col in ii_data.columns:
                    fig_cum.add_trace(
                        go.Scatter(
                            x=ii_data["date"],
                            y=ii_data[col],
                            mode="lines",
                            name=col.replace("累積", "（累積）"),
                            line=dict(color=color, width=2),
                        )
                    )
            fig_cum.update_layout(
                title="三大法人累積買賣超（單位：張）",
                xaxis_title="日期",
                yaxis_title="累積買賣超（張）",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                template="plotly_dark",
                height=300,
            )
            st.plotly_chart(fig_cum, use_container_width=True)

            # 摘要指標
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "外資累積買賣超",
                f"{ii_data['外資買賣超'].sum():,.0f} 張",
                help="正值=分析期間外資累積買超，負值=賣超",
            )
            c2.metric(
                "投信累積買賣超",
                f"{ii_data['投信買賣超'].sum():,.0f} 張",
            )
            c3.metric(
                "自營商累積買賣超",
                f"{ii_data['自營商買賣超'].sum():,.0f} 張",
            )
        else:
            st.info(
                "ℹ️ 三大法人資料無法取得。\n\n"
                "可能原因：\n"
                "1. 尚未輸入 FinMind Token（免費註冊：https://finmindtrade.com）\n"
                "2. 所選日期範圍無三大法人資料"
            )

        # ── F-005 基本統計資訊 ───────────────────────
        st.subheader("📋 基本統計資訊")

        start_price = float(stock_data["close"].iloc[0])
        end_price   = float(stock_data["close"].iloc[-1])
        abs_change  = end_price - start_price
        pct_change  = abs_change / start_price * 100

        col1, col2, col3 = st.columns(3)
        col1.metric(
            label="起始價格",
            value=f"NT${start_price:.2f}",
            help=f"分析期間第一個交易日（{stock_data['date'].iloc[0].strftime('%Y-%m-%d')}）收盤價",
        )
        col2.metric(
            label="結束價格",
            value=f"NT${end_price:.2f}",
            help=f"分析期間最後一個交易日（{stock_data['date'].iloc[-1].strftime('%Y-%m-%d')}）收盤價",
        )
        col3.metric(
            label="期間價格變化",
            value=f"{pct_change:+.2f}%",
            delta=f"NT${abs_change:+.2f}",
            delta_color="normal",
        )

        # ── 月營收圖表 ───────────────────────────────
        st.subheader("📈 月營收（近兩年）")
        if not rev_data.empty:
            fig_rev = go.Figure()
            fig_rev.add_trace(go.Bar(
                x=rev_data["date"],
                y=rev_data["revenue"],
                name="月營收（千元）",
                marker_color="#42A5F5",
                opacity=0.85,
                yaxis="y1",
            ))
            fig_rev.add_trace(go.Scatter(
                x=rev_data["date"],
                y=rev_data["yoy"],
                name="年增率（%）",
                mode="lines+markers",
                line=dict(color="#FF7043", width=2),
                yaxis="y2",
            ))
            fig_rev.update_layout(
                title=f"{symbol_input} {stock_name} 月營收與年增率",
                xaxis_title="年月",
                yaxis=dict(title="月營收（千元）", side="left"),
                yaxis2=dict(
                    title="年增率（%）",
                    side="right",
                    overlaying="y",
                    zeroline=True,
                    zerolinecolor="#888",
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                template="plotly_dark",
                height=380,
            )
            st.plotly_chart(fig_rev, use_container_width=True)
        else:
            st.info("ℹ️ 月營收資料無法取得（需要 FinMind Token 或該股無此資料）")

        # ── 季EPS / 年EPS 圖表 ──────────────────────
        st.subheader("💰 EPS（近兩年）")
        if not eps_q.empty or not eps_y.empty:
            eps_col1, eps_col2 = st.columns(2)

            with eps_col1:
                if not eps_q.empty:
                    fig_eps_q = go.Figure()
                    bar_colors = ["#EF5350" if v >= 0 else "#26A69A" for v in eps_q["eps"]]
                    fig_eps_q.add_trace(go.Bar(
                        x=eps_q["date"].dt.year.astype(str) + "-Q" + eps_q["date"].dt.quarter.astype(str),
                        y=eps_q["eps"],
                        name="季EPS",
                        marker_color=bar_colors,
                    ))
                    fig_eps_q.update_layout(
                        title="季EPS（元）",
                        xaxis_title="季度",
                        yaxis_title="EPS（元）",
                        template="plotly_dark",
                        height=320,
                    )
                    st.plotly_chart(fig_eps_q, use_container_width=True)
                else:
                    st.info("ℹ️ 季EPS資料無法取得")

            with eps_col2:
                if not eps_y.empty:
                    fig_eps_y = go.Figure()
                    bar_colors_y = ["#EF5350" if v >= 0 else "#26A69A" for v in eps_y["eps"]]
                    fig_eps_y.add_trace(go.Bar(
                        x=eps_y["date"].dt.strftime("%Y"),
                        y=eps_y["eps"],
                        name="年EPS",
                        marker_color=bar_colors_y,
                    ))
                    fig_eps_y.update_layout(
                        title="年EPS（元）",
                        xaxis_title="年度",
                        yaxis_title="EPS（元）",
                        template="plotly_dark",
                        height=320,
                    )
                    st.plotly_chart(fig_eps_y, use_container_width=True)
                else:
                    st.info("ℹ️ 年EPS資料無法取得")
        else:
            st.info("ℹ️ EPS資料無法取得（需要 FinMind Token 或該股無此資料）")

        # ── F-007 歷史數據表格 ───────────────────────
        st.subheader("📅 最近 10 筆交易日資料")

        display_df = stock_data.copy()
        display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
        display_df["volume"] = (display_df["volume"] / 1000).round(0).astype(int)
        display_df = display_df.rename(columns={
            "date":   "日期",
            "open":   "開盤價",
            "high":   "最高價",
            "low":    "最低價",
            "close":  "收盤價",
            "volume": "成交量(張)",
        })

        show_cols = ["日期", "開盤價", "最高價", "最低價", "收盤價", "成交量(張)",
                     "MA5", "MA10", "MA20", "MA60"]
        show_cols = [c for c in show_cols if c in display_df.columns]

        st.dataframe(
            display_df[show_cols].iloc[::-1].head(10).reset_index(drop=True),
            use_container_width=True,
        )

        # ── 一鍵匯出股價資料 ─────────────────────────
        st.markdown("---")
        st.subheader("📥 匯出資料")
        export_df = display_df[show_cols].iloc[::-1].reset_index(drop=True)
        # 加入三大法人資料
        if not ii_data.empty:
            ii_export = ii_data[["date", "外資買賣超", "投信買賣超", "自營商買賣超",
                                  "外資累積", "投信累積", "自營商累積"]].copy()
            ii_export["date"] = ii_export["date"].dt.strftime("%Y-%m-%d")
            ii_export = ii_export.rename(columns={"date": "日期"})
            merged_export = export_df.merge(ii_export, on="日期", how="left")
        else:
            merged_export = export_df

        csv_bytes = dataframe_to_csv_bytes(merged_export)
        dl_col, save_col = st.columns(2)
        with dl_col:
            st.download_button(
                label="⬇️ 下載股價 + 法人資料（CSV）",
                data=csv_bytes,
                file_name=f"{symbol_input}_{stock_name}_{start_date}_{end_date}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with save_col:
            if st.button("💾 儲存技術面資料到分析記錄", use_container_width=True):
                save_path = ANALYSIS_DIR / f"{symbol_input}_{stock_name}_{start_date}_{end_date}_技術面.csv"
                merged_export.to_csv(save_path, index=False, encoding=CSV_ENCODING)
                st.success(f"✅ 已儲存到 analysis/{save_path.name}")

    # ────────────────────────────────────────────
    # TAB 2：AI 綜合分析（獨立完整頁面）
    # ────────────────────────────────────────────
    with tab2:
        st.subheader("🤖 AI 綜合分析（Groq + Llama 3.3 70B）")
        st.caption("AI 同時整合 FinMind 量化數據與即時新聞進行分析，所有內容僅供教育研究參考。")

        if "_ai_report" not in st.session_state:
            with st.spinner("正在抓取近一年即時新聞（Google News）..."):
                news_data = get_stock_news(symbol_input, stock_name)
            if news_data:
                st.caption(f"📰 已抓取 {len(news_data)} 則近一年新聞供 AI 參考")
            else:
                st.caption("⚠️ 新聞抓取失敗，AI 將依訓練資料分析")

            with st.spinner("AI 正在分析台股數據，請稍候（約 10-20 秒）..."):
                ai_report = generate_ai_insights(
                    full_symbol, stock_name, stock_data, ii_data, groq_api_key,
                    rev_data=rev_data, eps_q=eps_q, eps_y=eps_y,
                    gross_margin_data=gross_margin_data,
                    foreign_holding_data=foreign_holding_data,
                    news_data=news_data,
                    taiex_change=taiex_change,
                )
            st.session_state["_ai_report"] = ai_report
            st.session_state["_news_data"] = news_data
        else:
            ai_report = st.session_state["_ai_report"]
            news_data = st.session_state.get("_news_data", [])
            if news_data:
                st.caption(f"📰 已抓取 {len(news_data)} 則近一年新聞供 AI 參考")

        if ai_report:
            st.markdown(ai_report)

            # ── 一鍵匯出 AI 報告 ──────────────────────
            st.markdown("---")
            report_header = (
                f"# {symbol_input} {stock_name} AI 台股分析報告\n"
                f"分析期間：{start_date} ～ {end_date}\n"
                f"產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                "---\n\n"
            )
            report_full = report_header + ai_report + "\n\n---\n免責聲明：本報告由 AI 產生，僅供教育研究參考，不構成投資建議。\n"
            ai_dl_col, ai_save_col = st.columns(2)
            with ai_dl_col:
                st.download_button(
                    label="⬇️ 下載 AI 分析報告（Markdown）",
                    data=report_full.encode("utf-8"),
                    file_name=f"{symbol_input}_{stock_name}_AI報告_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                    mime="text/markdown",
                    use_container_width=True,
                )
            with ai_save_col:
                if st.button("💾 儲存 AI 報告到分析記錄", use_container_width=True):
                    ts = datetime.now().strftime("%Y%m%d_%H%M")
                    save_path = ANALYSIS_DIR / f"{symbol_input}_{stock_name}_AI報告_{ts}.md"
                    save_path.write_text(report_full, encoding="utf-8")
                    st.success(f"✅ 已儲存到 analysis/{save_path.name}")

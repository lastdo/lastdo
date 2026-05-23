import json
import requests
import streamlit as st
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px

from _app_common import FINMIND_URL, configure_runtime, get_portfolio_file
from _style import apply_style, render_global_navigation

configure_runtime()

BROKER_FEE_RATE = 0.001425
STOCK_SELL_TAX_RATE = 0.003

@st.cache_data(ttl=3600)
def fetch_all_stock_names() -> dict:
    try:
        resp = requests.get(FINMIND_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        result = resp.json()
        if result.get("status") == 200 and result.get("data"):
            return {row["stock_id"]: row.get("stock_name", "") for row in result["data"]}
    except Exception:
        pass
    return {}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_recent_stock_price(symbol: str) -> dict:
    end_date = datetime.today().date()
    start_date = end_date - timedelta(days=21)
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": symbol,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    try:
        resp = requests.get(FINMIND_URL, params=params, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("status") != 200 or not result.get("data"):
            return {}

        df = pd.DataFrame(result["data"])
        if df.empty or "close" not in df.columns:
            return {}
        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values("date")
        if df.empty:
            return {}

        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) >= 2 else None
        latest_price = float(latest["close"])
        previous_price = float(previous["close"]) if previous is not None else None
        return {
            "latest_price": latest_price,
            "previous_price": previous_price,
            "price_date": latest["date"].strftime("%Y-%m-%d"),
        }
    except Exception:
        return {}

PORTFOLIO_FILE = get_portfolio_file()

st.set_page_config(page_title="庫存股管理", page_icon="💼", layout="wide")

# ── 全域樣式 ────────────────────────────────────────────────────────────────────
apply_style()
st.markdown("""
<style>
/* ── 背景 ── */

/* ── 頁首橫幅 ── */
.inv-header {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 55%, #1d4ed8 100%);
    border-radius: 16px;
    padding: 30px 36px;
    margin-bottom: 20px;
    box-shadow: 0 8px 32px rgba(15,23,42,0.25);
    display: flex;
    align-items: center;
    gap: 20px;
}
.inv-header-icon { font-size: 3rem; line-height: 1; }
.inv-header h1 {
    margin: 0 0 6px;
    color: #ffffff;
    font-size: 1.85rem;
    font-weight: 800;
    letter-spacing: -0.3px;
}
.inv-header p { margin: 0; color: #93c5fd; font-size: 0.88rem; }

/* ── 統計卡片 ── */
.stat-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 20px 22px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.07);
    border-top: 4px solid;
    height: 100%;
}
.stat-card.c-blue   { border-color: #2563eb; }
.stat-card.c-green  { border-color: #16a34a; }
.stat-card.c-purple { border-color: #7c3aed; }
.stat-card.c-red    { border-color: #dc2626; }
.stat-card.c-amber  { border-color: #d97706; }
.stat-card.c-slate  { border-color: #475569; }
.stat-label { color: #64748b; font-size: 0.75rem; font-weight: 700;
              text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 8px; }
.stat-value { color: #0f172a; font-size: 1.7rem; font-weight: 800; }
.stat-sub   { color: #94a3b8; font-size: 0.78rem; margin-top: 4px; }
.stat-value.pos { color: #dc2626; }
.stat-value.neg { color: #16a34a; }

/* ── 新增表單標題 ── */
/* ── 表單容器美化 ── */
/* ── 清單標題列 ── */
/* ── 每行欄標題 ── */
/* ── 股票代碼標籤 ── */
.sym-badge {
    display: inline-block;
    background: #dbeafe;
    color: #1d4ed8;
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: 1px;
}
/* ── 數值欄 ── */
.val-main  { color: #0f172a; font-size: 1rem; font-weight: 700; }
.val-label { color: #94a3b8; font-size: 0.72rem; margin-top: 2px; }

/* ── 隔線每行 ── */
/* ── 空狀態 ── */
/* ── 主要按鈕 ── */
/* ── 刪除按鈕（secondary） ── */
.stButton > button[kind="secondary"] {
    border-radius: 8px !important;
    border-color: #fca5a5 !important;
    color: #dc2626 !important;
    background: #fff5f5 !important;
    transition: all 0.18s ease !important;
}
.stButton > button[kind="secondary"]:hover {
    background: #fee2e2 !important;
    border-color: #dc2626 !important;
}

/* ── 隱藏預設 Streamlit 頁尾 ── */
</style>
""", unsafe_allow_html=True)


def load_portfolio() -> list:
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
            for stock in portfolio:
                stock["symbol"] = str(stock.get("symbol", "")).strip()
                stock["price"] = _to_float(stock.get("price"))
                stock["shares"] = _to_int(stock.get("shares"))
            return portfolio
    return []


def save_portfolio(portfolio: list) -> None:
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)


def update_portfolio_item(index: int, price=None, shares=None) -> None:
    portfolio = load_portfolio()
    if index < 0 or index >= len(portfolio):
        raise IndexError("portfolio index out of range")

    portfolio[index]["price"] = _to_float(price)
    portfolio[index]["shares"] = _to_int(shares)
    save_portfolio(portfolio)


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def format_money(value, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"NT$ {value:,.{digits}f}"


def format_pct(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.2f}%"


def pnl_class(value) -> str:
    if value is None or pd.isna(value) or value == 0:
        return ""
    return "pos" if value > 0 else "neg"


def pnl_color_style(value) -> str:
    if value is None or pd.isna(value) or value == 0:
        return ""
    return "color: #dc2626; font-weight: 700;" if value > 0 else "color: #16a34a; font-weight: 700;"


def estimate_fee(amount, rate: float) -> int | None:
    if amount is None or pd.isna(amount):
        return None
    return int(amount * rate)


def build_portfolio_rows(portfolio: list, stock_names: dict) -> pd.DataFrame:
    rows = []
    for stock in portfolio:
        symbol = str(stock.get("symbol", "")).strip()
        cost_price = _to_float(stock.get("price"))
        shares = _to_int(stock.get("shares"))
        is_holding = bool(cost_price and shares and cost_price > 0 and shares > 0)
        price_info = fetch_recent_stock_price(symbol) if symbol else {}
        latest_price = price_info.get("latest_price")
        previous_price = price_info.get("previous_price")

        invested_cost = cost_price * shares if is_holding else None
        market_value = latest_price * shares if is_holding and latest_price is not None else None
        gross_unrealized_pnl = (
            market_value - invested_cost
            if market_value is not None and invested_cost is not None
            else None
        )
        sell_fee = estimate_fee(market_value, BROKER_FEE_RATE)
        sell_tax = estimate_fee(market_value, STOCK_SELL_TAX_RATE)
        exit_cost = (
            sell_fee + sell_tax
            if sell_fee is not None and sell_tax is not None
            else None
        )
        unrealized_pnl = (
            gross_unrealized_pnl - exit_cost
            if gross_unrealized_pnl is not None and exit_cost is not None
            else gross_unrealized_pnl
        )
        unrealized_return = (
            unrealized_pnl / invested_cost * 100
            if unrealized_pnl is not None and invested_cost
            else None
        )
        today_pnl = (
            (latest_price - previous_price) * shares
            if is_holding and latest_price is not None and previous_price is not None
            else None
        )

        rows.append({
            "symbol": symbol,
            "name": stock_names.get(symbol, ""),
            "type": "持股" if is_holding else "自選股",
            "cost_price": cost_price,
            "shares": shares,
            "latest_price": latest_price,
            "previous_price": previous_price,
            "price_date": price_info.get("price_date", ""),
            "invested_cost": invested_cost,
            "market_value": market_value,
            "sell_fee": sell_fee,
            "sell_tax": sell_tax,
            "exit_cost": exit_cost,
            "gross_unrealized_pnl": gross_unrealized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_return": unrealized_return,
            "today_pnl": today_pnl,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    total_market = df["market_value"].dropna().sum()
    df["position_ratio"] = df["market_value"].apply(
        lambda value: value / total_market * 100
        if total_market and value is not None and not pd.isna(value)
        else None
    )
    return df


portfolio = load_portfolio()
stock_names = fetch_all_stock_names()
with st.sidebar:
    render_global_navigation("inventory")

# ── 頁首橫幅 ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="inv-header">
    <div class="inv-header-icon">💼</div>
    <div>
        <h1>庫存股管理系統</h1>
        <p>管理您的台股投資組合 &nbsp;·&nbsp; 一鍵跳轉 AI 趨勢分析</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ── 投組摘要 ──────────────────────────────────────────────────────────────────
with st.spinner("正在更新庫存股市值與損益..."):
    portfolio_df = build_portfolio_rows(portfolio, stock_names)

if portfolio_df.empty:
    holding_df = pd.DataFrame()
    watch_df = pd.DataFrame()
else:
    holding_df = portfolio_df[portfolio_df["type"] == "持股"].copy()
    watch_df = portfolio_df[portfolio_df["type"] == "自選股"].copy()

total_cost = holding_df["invested_cost"].dropna().sum() if not holding_df.empty else 0
total_market = holding_df["market_value"].dropna().sum() if not holding_df.empty else 0
unrealized_pnl = (
    holding_df["unrealized_pnl"].dropna().sum()
    if not holding_df.empty and holding_df["unrealized_pnl"].notna().any()
    else None
)
unrealized_return = unrealized_pnl / total_cost * 100 if unrealized_pnl is not None and total_cost else None
today_pnl = (
    holding_df["today_pnl"].dropna().sum()
    if not holding_df.empty and holding_df["today_pnl"].notna().any()
    else None
)
priced_holding_count = int(holding_df["market_value"].notna().sum()) if not holding_df.empty else 0

total_exit_cost = holding_df["exit_cost"].dropna().sum() if not holding_df.empty else 0

summary_cards = [
    ("總投入成本", format_money(total_cost), f"{len(holding_df)} 檔持股", "c-green", ""),
    ("目前總市值", format_money(total_market), f"{priced_holding_count} 檔已取得最新收盤價", "c-blue", ""),
    ("未實現損益", format_money(unrealized_pnl), f"已扣預估賣出費稅 {format_money(total_exit_cost)}", "c-red" if (unrealized_pnl or 0) >= 0 else "c-green", pnl_class(unrealized_pnl)),
    ("未實現報酬率", format_pct(unrealized_return), "淨損益 / 總投入成本", "c-purple", pnl_class(unrealized_return)),
    ("今日損益", format_money(today_pnl), "最新收盤價 - 前一交易日收盤價", "c-amber", pnl_class(today_pnl)),
]

for row in [summary_cards[:3], summary_cards[3:]]:
    cols = st.columns(len(row))
    for col, (label, value, sub, color, value_class) in zip(cols, row):
        with col:
            st.markdown(f"""
            <div class="stat-card {color}">
                <div class="stat-label">{label}</div>
                <div class="stat-value {value_class}" style="font-size:1.35rem;">{value}</div>
                <div class="stat-sub">{sub}</div>
            </div>""", unsafe_allow_html=True)

# ── 新增持股表單 ───────────────────────────────────────────────────────────────
st.markdown('<div class="form-section-title">新增自選股 / 持股</div>', unsafe_allow_html=True)

with st.form("add_stock_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1.2])
    with col1:
        new_symbol = st.text_input("股票代碼", placeholder="例：2330")
    with col2:
        new_price = st.text_input("持有成本價（選填）", placeholder="例：150.5")
    with col3:
        new_shares = st.text_input("持有股數（選填）", placeholder="例：1000")
    with col4:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        submitted = st.form_submit_button("＋ 新增", use_container_width=True, type="primary")

if submitted:
    new_symbol = new_symbol.strip()
    if not new_symbol:
        st.error("❌ 請輸入股票代碼")
    elif not new_symbol.isdigit():
        st.error("❌ 股票代碼需為純數字（例：2330、0050）")
    elif any(s["symbol"] == new_symbol for s in portfolio):
        st.warning(f"⚠️「{new_symbol}」已在庫存清單中")
    else:
        try:
            price_val = float(new_price.strip()) if new_price.strip() else None
        except ValueError:
            price_val = None
        try:
            shares_val = int(new_shares.strip()) if new_shares.strip() else None
        except ValueError:
            shares_val = None
        new_item = {"symbol": new_symbol, "price": price_val, "shares": shares_val}
        portfolio.append(new_item)
        save_portfolio(portfolio)
        item_type = "持股" if price_val and shares_val else "自選股"
        st.success(f"✅ 已新增「{new_symbol}」{stock_names.get(new_symbol, '')} 至{item_type}清單")
        st.rerun()

# ── 個股持倉比例 ───────────────────────────────────────────────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

if not holding_df.empty and holding_df["market_value"].notna().any():
    st.markdown('<div class="form-section-title">個股持倉比例</div>', unsafe_allow_html=True)
    chart_df = holding_df.dropna(subset=["market_value"]).copy()
    chart_df["label"] = chart_df["symbol"] + " " + chart_df["name"].fillna("")
    chart_df = chart_df.sort_values("position_ratio", ascending=True)
    chart_df["ratio_label"] = chart_df["position_ratio"].map(lambda x: f"{x:.1f}%")
    chart_df["bar_color"] = chart_df["unrealized_pnl"].apply(
        lambda value: "#dc2626" if pd.notna(value) and value > 0 else "#16a34a"
    )
    fig = px.bar(
        chart_df,
        x="position_ratio",
        y="label",
        orientation="h",
        text="ratio_label",
        color="bar_color",
        color_discrete_map="identity",
        labels={"position_ratio": "持倉比例 (%)", "label": "股票"},
        height=max(260, 48 * len(chart_df) + 90),
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        margin=dict(l=10, r=60, t=24, b=10),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

# ── 自選股 / 持股清單 ─────────────────────────────────────────────────────────
if not portfolio:
    st.markdown("""
    <div class="empty-state">
        <div class="es-icon">📭</div>
        <h3>庫存清單是空的</h3>
        <p>在上方輸入股票代碼，按「新增」開始建立自選股或持股清單</p>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown('<div class="form-section-title">持股清單</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="list-header">
        <span>持股清單</span>
        <span class="lh-count">{len(holding_df)} 檔</span>
    </div>""", unsafe_allow_html=True)

    if holding_df.empty:
        st.info("目前沒有填入成本與股數的持股；只有股票代碼會歸在下方自選股。")
    else:
        display_holding_df = holding_df.copy()
        display_holding_df = display_holding_df.sort_values("market_value", ascending=False, na_position="last")
        raw_holding_df = display_holding_df.copy()
        display_holding_df["股票"] = display_holding_df["symbol"] + " " + display_holding_df["name"].fillna("")
        display_holding_df["持有成本"] = display_holding_df["cost_price"].map(lambda x: format_money(x, 2))
        display_holding_df["股數"] = display_holding_df["shares"].map(lambda x: f"{int(x):,} 股" if pd.notna(x) else "—")
        display_holding_df["最新價"] = display_holding_df["latest_price"].map(lambda x: format_money(x, 2))
        display_holding_df["投入成本"] = display_holding_df["invested_cost"].map(format_money)
        display_holding_df["目前市值"] = display_holding_df["market_value"].map(format_money)
        display_holding_df["毛損益"] = display_holding_df["gross_unrealized_pnl"].map(format_money)
        display_holding_df["賣出手續費"] = display_holding_df["sell_fee"].map(format_money)
        display_holding_df["交易稅"] = display_holding_df["sell_tax"].map(format_money)
        display_holding_df["未實現損益"] = display_holding_df["unrealized_pnl"].map(format_money)
        display_holding_df["未實現報酬率"] = display_holding_df["unrealized_return"].map(format_pct)
        display_holding_df["今日損益"] = display_holding_df["today_pnl"].map(format_money)
        display_holding_df["持倉比例"] = display_holding_df["position_ratio"].map(
            lambda x: f"{x:.2f}%" if pd.notna(x) else "—"
        )
        display_holding_df["價格日"] = display_holding_df["price_date"].replace("", "—")
        display_columns = [
            "股票",
            "持有成本",
            "股數",
            "最新價",
            "投入成本",
            "目前市值",
            "毛損益",
            "賣出手續費",
            "交易稅",
            "未實現損益",
            "未實現報酬率",
            "今日損益",
            "持倉比例",
            "價格日",
        ]
        styled_holding_df = display_holding_df[display_columns].style
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in raw_holding_df["gross_unrealized_pnl"]],
            subset=["毛損益"],
        )
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in raw_holding_df["unrealized_pnl"]],
            subset=["未實現損益"],
        )
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in raw_holding_df["unrealized_return"]],
            subset=["未實現報酬率"],
        )
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in raw_holding_df["today_pnl"]],
            subset=["今日損益"],
        )
        st.dataframe(
            styled_holding_df,
            use_container_width=True,
            hide_index=True,
        )

    st.markdown('<div class="form-section-title">自選股清單</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="list-header">
        <span>自選股清單</span>
        <span class="lh-count">{len(watch_df)} 檔</span>
    </div>""", unsafe_allow_html=True)

    if watch_df.empty:
        st.info("目前沒有自選股；新增股票時不填成本與股數，就會放到自選股清單。")
    else:
        watch_display = watch_df.copy()
        watch_display["股票"] = watch_display["symbol"] + " " + watch_display["name"].fillna("")
        watch_display["最新價"] = watch_display["latest_price"].map(lambda x: format_money(x, 2))
        watch_display["前收"] = watch_display["previous_price"].map(lambda x: format_money(x, 2))
        watch_display["價格日"] = watch_display["price_date"].replace("", "—")
        st.dataframe(
            watch_display[["股票", "最新價", "前收", "價格日"]],
            use_container_width=True,
            hide_index=True,
        )

    st.markdown('<div class="form-section-title">操作</div>', unsafe_allow_html=True)
    h0, h1, h2, h3, h4, h5 = st.columns([0.4, 1.1, 1.7, 1.0, 2.5, 2.7])
    h0.markdown('<div class="col-hdr">#</div>', unsafe_allow_html=True)
    h1.markdown('<div class="col-hdr">代碼</div>', unsafe_allow_html=True)
    h2.markdown('<div class="col-hdr">股票名稱</div>', unsafe_allow_html=True)
    h3.markdown('<div class="col-hdr">類型</div>', unsafe_allow_html=True)
    h4.markdown('<div class="col-hdr">成本 / 股數</div>', unsafe_allow_html=True)
    h5.markdown('<div class="col-hdr">操作</div>', unsafe_allow_html=True)

    for i, stock in enumerate(portfolio):
        symbol = str(stock.get("symbol", ""))
        matched = portfolio_df[portfolio_df["symbol"] == symbol]
        item_type = matched.iloc[0]["type"] if not matched.empty else "自選股"
        name = stock_names.get(symbol, "")
        default_price = _to_float(stock.get("price"))
        default_shares = _to_int(stock.get("shares"))

        c0, c1, c2, c3, c4, c5 = st.columns([0.4, 1.1, 1.7, 1.0, 2.5, 2.7])
        with c0:
            st.markdown(f"<div style='color:#cbd5e1;font-size:0.8rem;padding-top:10px;text-align:center'>{i+1}</div>", unsafe_allow_html=True)
        with c1:
            st.markdown(f"<div style='padding-top:6px'><span class='sym-badge'>{symbol}</span></div>", unsafe_allow_html=True)
        with c2:
            _name_html = name if name else "<span style='color:#cbd5e1'>—</span>"
            st.markdown(f"<div class='stock-name-text' style='padding-top:10px'>{_name_html}</div>", unsafe_allow_html=True)
        with c3:
            badge_class = "holding" if item_type == "持股" else "watch"
            st.markdown(f"<div style='padding-top:10px'><span class='status-badge {badge_class}'>{item_type}</span></div>", unsafe_allow_html=True)
        with c4:
            edit_col1, edit_col2 = st.columns(2)
            with edit_col1:
                edit_price = st.number_input(
                    "成本",
                    min_value=0.0,
                    step=0.1,
                    value=float(default_price or 0.0),
                    key=f"price_{i}",
                    label_visibility="collapsed",
                )
            with edit_col2:
                edit_shares = st.number_input(
                    "股數",
                    min_value=0,
                    step=1,
                    value=int(default_shares or 0),
                    key=f"shares_{i}",
                    label_visibility="collapsed",
                )
            if st.button("儲存", key=f"save_{i}", use_container_width=True):
                update_portfolio_item(
                    i,
                    price=edit_price if edit_price > 0 else None,
                    shares=edit_shares if edit_shares > 0 else None,
                )
                st.toast(f"已更新「{symbol}」的持股資料")
                st.rerun()
        with c5:
            btn_col1, btn_col2 = st.columns([3, 1])
            with btn_col1:
                if st.button("📈 AI 分析", key=f"analyze_{i}", use_container_width=True, type="primary"):
                    st.session_state["selected_symbol"] = symbol
                    st.switch_page("pages/1_app_tw.py")
            with btn_col2:
                if st.button("🗑️", key=f"del_{i}", help=f"移除 {symbol}"):
                    removed = portfolio.pop(i)
                    save_portfolio(portfolio)
                    st.toast(f"✅ 已移除「{removed['symbol']}」")
                    st.rerun()

        st.markdown("<hr class='row-divider'>", unsafe_allow_html=True)

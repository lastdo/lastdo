import streamlit as st
from datetime import datetime
import re

import pandas as pd
import plotly.express as px

from _app_common import configure_runtime
from _market_api import fetch_json_tpex, fetch_json_twse
from _portfolio_store import (
    create_portfolio_item,
    delete_portfolio_item,
    get_default_family_id,
    get_google_sheet_edit_url,
    get_store_status,
    list_family_ids,
    load_portfolio as load_portfolio_items,
    update_portfolio_item as update_portfolio_record,
)
from _style import apply_style, render_global_navigation

configure_runtime()

BROKER_FEE_RATE = 0.001425
STOCK_SELL_TAX_RATE = 0.003
URL_TWSE_PRICE = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
URL_TPEX_PRICE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _parse_market_number(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "---", "----", "X", "除權息"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_price_date(raw_value) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return datetime.today().strftime("%Y-%m-%d")
    if len(text) == 7 and text.isdigit():
        year = int(text[:3]) + 1911
        return f"{year:04d}-{text[3:5]}-{text[5:7]}"
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if "/" in text:
        parts = text.split("/")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            year = int(parts[0])
            if year < 1911:
                year += 1911
            return f"{year:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return text


@st.cache_data(ttl=900, show_spinner=False)
def fetch_market_snapshot() -> tuple[dict, list[str]]:
    snapshot: dict[str, dict] = {}
    errors: list[str] = []

    try:
        raw_twse = fetch_json_twse(URL_TWSE_PRICE)
        twse_date = _normalize_price_date(raw_twse[0].get("Date") if raw_twse else None)
        df_twse = pd.DataFrame(raw_twse)
        if {"Code", "Name", "ClosingPrice"}.issubset(df_twse.columns):
            for row in df_twse.to_dict("records"):
                stock_id = str(row.get("Code", "")).strip()
                close_price = _parse_market_number(row.get("ClosingPrice"))
                change_value = _parse_market_number(row.get("Change"))
                previous_price = close_price - change_value if close_price is not None and change_value is not None else None
                if stock_id:
                    snapshot[stock_id] = {
                        "stock_name": str(row.get("Name", "")).strip(),
                        "latest_price": close_price,
                        "previous_price": previous_price,
                        "price_date": twse_date,
                    }
    except Exception as exc:
        errors.append(f"TWSE fetch failed: {type(exc).__name__}")

    try:
        raw_tpex = fetch_json_tpex(URL_TPEX_PRICE)
        tpex_date = _normalize_price_date(raw_tpex[0].get("Date") if raw_tpex else None)
        df_tpex = pd.DataFrame(raw_tpex)
        if {"SecuritiesCompanyCode", "CompanyName", "Close"}.issubset(df_tpex.columns):
            for row in df_tpex.to_dict("records"):
                stock_id = str(row.get("SecuritiesCompanyCode", "")).strip()
                close_price = _parse_market_number(row.get("Close"))
                change_value = _parse_market_number(
                    row.get("Change")
                    or row.get("Spread")
                    or row.get("PriceChange")
                )
                previous_price = close_price - change_value if close_price is not None and change_value is not None else None
                if stock_id:
                    snapshot[stock_id] = {
                        "stock_name": str(row.get("CompanyName", "")).strip(),
                        "latest_price": close_price,
                        "previous_price": previous_price,
                        "price_date": tpex_date,
                    }
    except Exception as exc:
        errors.append(f"TPEX fetch failed: {type(exc).__name__}")

    return snapshot, errors


st.set_page_config(page_title="庫存股管理", page_icon="💼", layout="wide")

# ── 全域樣式 ────────────────────────────────────────────────────────────────────
apply_style()
st.markdown("""
<style>
/* ── 背景 ── */

/* ── 頁首橫幅 ── */
.inv-header {
    background: linear-gradient(135deg, var(--bg-header-start) 0%, var(--bg-header-mid) 55%, var(--bg-header-end) 100%);
    border-radius: 16px;
    padding: 30px 36px;
    margin-bottom: 20px;
    box-shadow: var(--shadow-hero);
    display: flex;
    align-items: center;
    gap: 20px;
}
.inv-header-icon { font-size: 3rem; line-height: 1; }
.inv-header h1 {
    margin: 0 0 6px;
    color: var(--text-on-header);
    font-size: 1.85rem;
    font-weight: 800;
    letter-spacing: -0.3px;
}
.inv-header p { margin: 0; color: #bfdbfe; font-size: 0.88rem; }

/* ── 統計卡片 ── */
.stat-card {
    background: var(--bg-surface);
    border-radius: 12px;
    padding: 20px 22px;
    box-shadow: var(--shadow-soft);
    border-top: 4px solid;
    height: 100%;
}
.stat-card.c-blue   { border-color: var(--accent-primary); }
.stat-card.c-green  { border-color: var(--accent-positive); }
.stat-card.c-purple { border-color: #7c3aed; }
.stat-card.c-red    { border-color: var(--accent-risk); }
.stat-card.c-amber  { border-color: var(--accent-warn); }
.stat-card.c-slate  { border-color: var(--accent-neutral); }
.stat-label { color: var(--text-secondary); font-size: 0.75rem; font-weight: 700;
              text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 8px; }
.stat-value { color: var(--text-primary); font-size: 1.7rem; font-weight: 800; }
.stat-sub   { color: var(--text-muted); font-size: 0.78rem; margin-top: 4px; }
.stat-value.pos { color: var(--accent-risk); }
.stat-value.neg { color: var(--accent-positive); }

/* ── 新增表單標題 ── */
/* ── 表單容器美化 ── */
/* ── 清單標題列 ── */
/* ── 每行欄標題 ── */
/* ── 股票代碼標籤 ── */
.sym-badge {
    display: inline-block;
    background: var(--accent-primary-soft);
    color: var(--bg-header-end);
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: 1px;
}
/* ── 數值欄 ── */
.val-main  { color: var(--text-primary); font-size: 1rem; font-weight: 700; }
.val-label { color: var(--text-muted); font-size: 0.72rem; margin-top: 2px; }

/* ── 隔線每行 ── */
/* ── 空狀態 ── */
/* ── 主要按鈕 ── */
/* ── 刪除按鈕（secondary） ── */
.stButton > button[kind="secondary"] {
    border-radius: 8px !important;
    border-color: #f1a9a0 !important;
    color: var(--accent-risk) !important;
    background: #fff5f5 !important;
    transition: all 0.18s ease !important;
}
.stButton > button[kind="secondary"]:hover {
    background: var(--accent-risk-soft) !important;
    border-color: var(--accent-risk) !important;
}


/* ── 隱藏預設 Streamlit 頁尾 ── */
</style>
""", unsafe_allow_html=True)


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


def format_signed_money(value, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}NT$ {value:,.{digits}f}"


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


def build_portfolio_rows(portfolio: list, stock_names: dict, market_snapshot: dict) -> pd.DataFrame:
    rows = []
    for stock in portfolio:
        symbol = str(stock.get("symbol", "")).strip()
        cost_price = _to_float(stock.get("price"))
        shares = _to_int(stock.get("shares"))
        is_holding = bool(cost_price and shares and cost_price > 0 and shares > 0)
        price_info = market_snapshot.get(symbol, {}) if symbol else {}
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
            "row_id": str(stock.get("row_id", "")).strip(),
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


if st.session_state.pop("refresh_market_snapshot", False):
    fetch_market_snapshot.clear()

market_snapshot, market_snapshot_errors = fetch_market_snapshot()
stock_names = {
    stock_id: info.get("stock_name", "")
    for stock_id, info in market_snapshot.items()
}
store_status = get_store_status()
known_family_ids = list_family_ids()
with st.sidebar:
    render_global_navigation("inventory")
    st.markdown("---")
    st.text_input(
        "family_id",
        value=st.session_state.get("inventory_family_id", get_default_family_id()),
        key="inventory_family_id",
        help="同一份 Google Sheet 內用 family_id 區分不同家人的持股。",
    )
    if st.button("重新抓取行情", use_container_width=True):
        st.session_state["refresh_market_snapshot"] = True
        st.rerun()
    if known_family_ids:
        st.caption("已知 family_id：" + ", ".join(known_family_ids[:8]))
    if store_status.using_google_sheets:
        st.caption("持股儲存：Google Sheets")
        _sheet_edit_url = get_google_sheet_edit_url()
        if _sheet_edit_url:
            st.markdown(f"[開啟 Google Sheet 編輯庫存](<{_sheet_edit_url}>)")
            st.caption("請切到 holdings 工作表編輯；家人需先取得該 Sheet 的編輯權限。")
    elif store_status.configured:
        st.caption("持股儲存：本機 portfolio.json")
    else:
        st.warning(store_status.message)

family_id = st.session_state.get("inventory_family_id", get_default_family_id()).strip()
if not FAMILY_ID_PATTERN.fullmatch(family_id):
    st.error("family_id 格式錯誤：只允許英數、底線(_)與減號(-)，長度 1-64。")
    st.stop()
portfolio = load_portfolio_items(family_id)

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
    portfolio_df = build_portfolio_rows(portfolio, stock_names, market_snapshot)

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

missing_price_symbols = []
if not holding_df.empty:
    missing_price_symbols = sorted(
        holding_df.loc[holding_df["latest_price"].isna(), "symbol"].astype(str).tolist()
    )

if market_snapshot_errors:
    st.warning(
        "行情快照抓取不完整："
        + " | ".join(market_snapshot_errors)
        + "。可先按一次「重新抓取行情」。"
    )
elif missing_price_symbols:
    st.warning(
        f"目前有 {len(missing_price_symbols)} 檔持股沒有對到最新價："
        + ", ".join(missing_price_symbols[:12])
        + "。可先按一次「重新抓取行情」確認是否為暫時性 API 問題。"
    )

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
        create_portfolio_item(
            family_id=family_id,
            stock_id=new_symbol,
            avg_cost=price_val,
            shares=shares_val,
            stock_name=stock_names.get(new_symbol, ""),
        )
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
        lambda value: "#d92d20" if pd.notna(value) and value > 0 else "#18804b"
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
        plot_bgcolor="white",
        paper_bgcolor="white",
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
        display_holding_df["股票"] = display_holding_df["symbol"] + " " + display_holding_df["name"].fillna("")
        display_holding_df["持有成本"] = display_holding_df["cost_price"]
        display_holding_df["股數"] = display_holding_df["shares"]
        display_holding_df["最新價"] = display_holding_df["latest_price"]
        display_holding_df["投入成本"] = display_holding_df["invested_cost"]
        display_holding_df["目前市值"] = display_holding_df["market_value"]
        display_holding_df["毛損益"] = display_holding_df["gross_unrealized_pnl"]
        display_holding_df["賣出手續費"] = display_holding_df["sell_fee"]
        display_holding_df["交易稅"] = display_holding_df["sell_tax"]
        display_holding_df["未實現損益"] = display_holding_df["unrealized_pnl"]
        display_holding_df["未實現報酬率"] = display_holding_df["unrealized_return"]
        display_holding_df["今日損益"] = display_holding_df["today_pnl"]
        display_holding_df["持倉比例"] = display_holding_df["position_ratio"]
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
        styled_holding_df = display_holding_df[display_columns].style.format({
            "持有成本": lambda x: format_money(x, 2),
            "股數": lambda x: f"{int(x):,} 股" if pd.notna(x) else "—",
            "最新價": lambda x: format_money(x, 2),
            "投入成本": format_money,
            "目前市值": format_money,
            "毛損益": format_signed_money,
            "賣出手續費": format_money,
            "交易稅": format_money,
            "未實現損益": format_signed_money,
            "未實現報酬率": format_pct,
            "今日損益": format_signed_money,
            "持倉比例": lambda x: f"{x:.2f}%" if pd.notna(x) else "—",
        })
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in display_holding_df["gross_unrealized_pnl"]],
            subset=["毛損益"],
        )
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in display_holding_df["unrealized_pnl"]],
            subset=["未實現損益"],
        )
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in display_holding_df["unrealized_return"]],
            subset=["未實現報酬率"],
        )
        styled_holding_df = styled_holding_df.apply(
            lambda col: [pnl_color_style(v) for v in display_holding_df["today_pnl"]],
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

    with st.expander("管理持股 / 自選股", expanded=False):
        st.markdown('<div class="form-section-title">操作</div>', unsafe_allow_html=True)
        h0, h1, h2, h3, h4, h5 = st.columns([0.4, 1.1, 1.7, 1.0, 2.5, 2.7])
        h0.markdown('<div class="col-hdr">#</div>', unsafe_allow_html=True)
        h1.markdown('<div class="col-hdr">代碼</div>', unsafe_allow_html=True)
        h2.markdown('<div class="col-hdr">股票名稱</div>', unsafe_allow_html=True)
        h3.markdown('<div class="col-hdr">類型</div>', unsafe_allow_html=True)
        h4.markdown('<div class="col-hdr">成本 / 股數</div>', unsafe_allow_html=True)
        h5.markdown('<div class="col-hdr">操作</div>', unsafe_allow_html=True)

        for i, stock in enumerate(portfolio):
            row_id = str(stock.get("row_id", "")).strip()
            symbol = str(stock.get("symbol", ""))
            matched = portfolio_df[portfolio_df["row_id"] == row_id]
            item_type = matched.iloc[0]["type"] if not matched.empty else "自選股"
            name = stock_names.get(symbol, "")
            default_price = _to_float(stock.get("price"))
            default_shares = _to_int(stock.get("shares"))

            c0, c1, c2, c3, c4, c5 = st.columns([0.4, 1.1, 1.7, 1.0, 2.5, 2.7])
            with c0:
                st.markdown(f"<div style='color:var(--text-muted);font-size:0.8rem;padding-top:10px;text-align:center'>{i+1}</div>", unsafe_allow_html=True)
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
                    update_portfolio_record(
                        row_id=row_id,
                        family_id=family_id,
                        avg_cost=edit_price if edit_price > 0 else None,
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
                        delete_portfolio_item(row_id=row_id, family_id=family_id)
                        st.toast(f"✅ 已移除「{symbol}」")
                        st.rerun()

            st.markdown("<hr class='row-divider'>", unsafe_allow_html=True)

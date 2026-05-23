import logging

class _IgnoreBareMode(logging.Filter):
    def filter(self, record):
        return "missing ScriptRunContext" not in record.getMessage()

logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context"
).addFilter(_IgnoreBareMode())

import json
import requests
import streamlit as st
from pathlib import Path

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

@st.cache_data(ttl=3600)
def fetch_all_stock_names() -> dict:
    """一次取得所有台股名稱對照表（不需要 Token），快取 1 小時。"""
    try:
        resp = requests.get(
            FINMIND_URL,
            params={"dataset": "TaiwanStockInfo"},
            timeout=15,
        )
        result = resp.json()
        if result.get("status") == 200 and result.get("data"):
            return {row["stock_id"]: row.get("stock_name", "") for row in result["data"]}
    except Exception:
        pass
    return {}

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

st.set_page_config(
    page_title="庫存股管理",
    page_icon="💼",
    layout="wide",
)


def load_portfolio() -> list:
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_portfolio(portfolio: list) -> None:
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)


portfolio = load_portfolio()
stock_names = fetch_all_stock_names()

st.title("💼 庫存股管理")
st.caption("點擊「📈 分析」可跳轉至 AI 台股趨勢分析系統，並自動帶入股票代碼")
st.divider()

# ── 新增股票 ──────────────────────────────────────
with st.form("add_stock_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])
    with col1:
        new_symbol = st.text_input("股票代碼", placeholder="例：2330")
    with col2:
        new_price = st.text_input("持有價格（選填）", placeholder="例：150.5")
    with col3:
        new_shares = st.text_input("持有股數（選填）", placeholder="例：1000")
    with col4:
        st.write("")
        st.write("")
        submitted = st.form_submit_button("➕ 新增", use_container_width=True, type="primary")

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
        portfolio.append({"symbol": new_symbol, "price": price_val, "shares": shares_val})
        save_portfolio(portfolio)
        st.success(f"✅ 已新增 {new_symbol}")
        st.rerun()

st.divider()

# ── 庫存清單 ──────────────────────────────────────
if not portfolio:
    st.info("📭 庫存清單為空，請在上方新增股票代碼。")
else:
    st.subheader(f"庫存清單（共 {len(portfolio)} 檔）")
    st.markdown("")

    # 表頭
    h1, h2, h3, h4, h5, h6 = st.columns([1.5, 2, 1.5, 1.5, 2, 1])
    h1.markdown("**代碼**")
    h2.markdown("**名稱**")
    h3.markdown("**持有價格**")
    h4.markdown("**持有股數**")
    h5.markdown("**操作**")
    h6.markdown("**刪除**")
    st.divider()

    for i, stock in enumerate(portfolio):
        col_sym, col_name, col_price, col_shares, col_analyze, col_del = st.columns([1.5, 2, 1.5, 1.5, 2, 1])

        with col_sym:
            st.markdown(f"<span style='font-size:1.3rem; font-weight:700;'>{stock['symbol']}</span>", unsafe_allow_html=True)

        with col_name:
            name = stock_names.get(stock["symbol"], "")
            st.markdown(f"<span style='font-size:1.3rem;'>{name if name else '—'}</span>", unsafe_allow_html=True)

        with col_price:
            price = stock.get("price")
            st.markdown(f"NT$ {price:,.2f}" if price is not None else "—")

        with col_shares:
            shares = stock.get("shares")
            st.markdown(f"{shares:,} 股" if shares is not None else "—")

        with col_analyze:
            if st.button(
                f"📈 分析 {stock['symbol']}",
                key=f"analyze_{i}",
                use_container_width=True,
                type="primary",
            ):
                st.session_state["selected_symbol"] = stock["symbol"]
                st.switch_page("pages/1_app_tw.py")

        with col_del:
            if st.button("🗑️", key=f"del_{i}", help=f"從清單移除 {stock['symbol']}"):
                removed = portfolio.pop(i)
                save_portfolio(portfolio)
                st.toast(f"已移除 {removed['symbol']}")
                st.rerun()

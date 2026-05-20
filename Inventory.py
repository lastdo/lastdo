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
    try:
        resp = requests.get(FINMIND_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        result = resp.json()
        if result.get("status") == 200 and result.get("data"):
            return {row["stock_id"]: row.get("stock_name", "") for row in result["data"]}
    except Exception:
        pass
    return {}

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"

st.set_page_config(page_title="庫存股管理", page_icon="💼", layout="wide")

# ── 全域樣式 ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── 背景 ── */
.stApp { background: #f0f4f8; }

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
.stat-label { color: #64748b; font-size: 0.75rem; font-weight: 700;
              text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 8px; }
.stat-value { color: #0f172a; font-size: 1.7rem; font-weight: 800; }
.stat-sub   { color: #94a3b8; font-size: 0.78rem; margin-top: 4px; }

/* ── 新增表單標題 ── */
.form-section-title {
    font-size: 0.95rem;
    font-weight: 700;
    color: #1e293b;
    margin: 24px 0 4px;
    padding-left: 4px;
    border-left: 3px solid #2563eb;
    padding-left: 10px;
}

/* ── 表單容器美化 ── */
div[data-testid="stForm"] {
    background: #ffffff;
    border-radius: 12px;
    padding: 20px 20px 12px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.07);
    border: 1px solid #e2e8f0;
}

/* ── 清單標題列 ── */
.list-header {
    background: #1e293b;
    border-radius: 10px 10px 0 0;
    padding: 11px 16px;
    margin-bottom: 2px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.list-header span { color: #94a3b8; font-size: 0.78rem; font-weight: 700;
                    text-transform: uppercase; letter-spacing: 0.07em; }
.list-header .lh-count {
    background: #2563eb;
    color: #fff;
    border-radius: 20px;
    padding: 1px 10px;
    font-size: 0.75rem;
    font-weight: 700;
    margin-left: auto;
}

/* ── 每行欄標題 ── */
.col-hdr {
    color: #94a3b8;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 10px 0 4px;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 6px;
}

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
.stock-name-text {
    color: #334155;
    font-size: 0.92rem;
    font-weight: 600;
    margin-top: 4px;
}

/* ── 數值欄 ── */
.val-main  { color: #0f172a; font-size: 1rem; font-weight: 700; }
.val-label { color: #94a3b8; font-size: 0.72rem; margin-top: 2px; }

/* ── 隔線每行 ── */
.row-divider {
    border: none;
    border-top: 1px solid #f1f5f9;
    margin: 4px 0;
}

/* ── 空狀態 ── */
.empty-state {
    text-align: center;
    padding: 64px 20px;
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.06);
}
.empty-state .es-icon { font-size: 3.5rem; }
.empty-state h3 { color: #475569; margin: 14px 0 6px; font-size: 1.1rem; }
.empty-state p  { color: #94a3b8; font-size: 0.88rem; }

/* ── 主要按鈕 ── */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8, #3b82f6) !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em !important;
    transition: all 0.18s ease !important;
    box-shadow: 0 2px 8px rgba(37,99,235,0.3) !important;
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 14px rgba(37,99,235,0.45) !important;
}

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
#MainMenu, footer { visibility: hidden; }
div[data-testid="stDecoration"] { display: none; }
</style>
""", unsafe_allow_html=True)


def load_portfolio() -> list:
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_portfolio(portfolio: list) -> None:
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)


def render_entry_navigation() -> None:
    """Keep Inventory.py as the main entry and restore access to all tools."""
    with st.sidebar:
        st.header("功能導覽")
        st.caption("這裡是主入口，可直接切換到分析、歷史與各種選股頁。")

        if st.button("📊 AI 台股分析", use_container_width=True, type="primary"):
            st.switch_page("pages/1_app_tw.py")
        if st.button("🕘 分析歷史", use_container_width=True):
            st.switch_page("pages/2_analysis_history.py")
        if st.button("📈 成長股篩選", use_container_width=True):
            st.switch_page("pages/3_growth_screener.py")
        if st.button("🏦 外資籌碼重壓", use_container_width=True):
            st.switch_page("pages/4_chip_screener.py")
        if st.button("🌱 底部剛起漲", use_container_width=True):
            st.switch_page("pages/5_bottom_screener.py")

        st.markdown("---")
        st.caption("目前頁面：💼 庫存股管理")


portfolio = load_portfolio()
stock_names = fetch_all_stock_names()
render_entry_navigation()

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

# ── 統計摘要 ──────────────────────────────────────────────────────────────────
total_stocks = len(portfolio)
priced = [s for s in portfolio if s.get("price") and s.get("shares")]
total_cost   = sum(s["price"] * s["shares"] for s in priced)
total_shares = sum(s["shares"] for s in priced)

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(f"""
    <div class="stat-card c-blue">
        <div class="stat-label">持股檔數</div>
        <div class="stat-value">{total_stocks}</div>
        <div class="stat-sub">檔股票在追蹤中</div>
    </div>""", unsafe_allow_html=True)
with c2:
    cost_str = f"NT$ {total_cost:,.0f}" if total_cost else "—"
    sub_str  = f"共 {len(priced)} 檔有填入成本" if priced else "尚未填入持有成本"
    st.markdown(f"""
    <div class="stat-card c-green">
        <div class="stat-label">持股總成本</div>
        <div class="stat-value" style="font-size:1.35rem;">{cost_str}</div>
        <div class="stat-sub">{sub_str}</div>
    </div>""", unsafe_allow_html=True)
with c3:
    shares_str = f"{total_shares:,} 股" if total_shares else "—"
    st.markdown(f"""
    <div class="stat-card c-purple">
        <div class="stat-label">持有股數合計</div>
        <div class="stat-value" style="font-size:1.35rem;">{shares_str}</div>
        <div class="stat-sub">{'約 {:,.1f} 張'.format(total_shares/1000) if total_shares else '尚未填入股數'}</div>
    </div>""", unsafe_allow_html=True)

# ── 新增持股表單 ───────────────────────────────────────────────────────────────
st.markdown('<div class="form-section-title">新增持股</div>', unsafe_allow_html=True)

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
        submitted = st.form_submit_button("＋ 新增持股", use_container_width=True, type="primary")

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
        st.success(f"✅ 已新增「{new_symbol}」{stock_names.get(new_symbol, '')} 至庫存清單")
        st.rerun()

# ── 庫存清單 ──────────────────────────────────────────────────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

if not portfolio:
    st.markdown("""
    <div class="empty-state">
        <div class="es-icon">📭</div>
        <h3>庫存清單是空的</h3>
        <p>在上方輸入股票代碼，按「新增持股」開始建立您的追蹤清單</p>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="list-header">
        <span>庫存清單</span>
        <span class="lh-count">{len(portfolio)} 檔</span>
    </div>""", unsafe_allow_html=True)

    # 欄標題列
    h0, h1, h2, h3, h4, h5 = st.columns([0.3, 1.6, 2.2, 1.8, 1.8, 2.5])
    h0.markdown('<div class="col-hdr">#</div>', unsafe_allow_html=True)
    h1.markdown('<div class="col-hdr">代碼</div>', unsafe_allow_html=True)
    h2.markdown('<div class="col-hdr">股票名稱</div>', unsafe_allow_html=True)
    h3.markdown('<div class="col-hdr">持有成本</div>', unsafe_allow_html=True)
    h4.markdown('<div class="col-hdr">持有股數</div>', unsafe_allow_html=True)
    h5.markdown('<div class="col-hdr">操作</div>', unsafe_allow_html=True)

    for i, stock in enumerate(portfolio):
        name   = stock_names.get(stock["symbol"], "")
        price  = stock.get("price")
        shares = stock.get("shares")

        c0, c1, c2, c3, c4, c5 = st.columns([0.3, 1.6, 2.2, 1.8, 1.8, 2.5])

        with c0:
            st.markdown(f"<div style='color:#cbd5e1;font-size:0.8rem;padding-top:10px;text-align:center'>{i+1}</div>", unsafe_allow_html=True)

        with c1:
            st.markdown(f"<div style='padding-top:6px'><span class='sym-badge'>{stock['symbol']}</span></div>", unsafe_allow_html=True)

        with c2:
            _name_html = name if name else "<span style='color:#cbd5e1'>—</span>"
            st.markdown(f"<div class='stock-name-text' style='padding-top:10px'>{_name_html}</div>", unsafe_allow_html=True)

        with c3:
            if price is not None:
                st.markdown(f"<div style='padding-top:8px'><div class='val-main'>NT$ {price:,.2f}</div><div class='val-label'>每股成本</div></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='padding-top:10px;color:#cbd5e1;font-size:0.9rem'>—</div>", unsafe_allow_html=True)

        with c4:
            if shares is not None:
                st.markdown(f"<div style='padding-top:8px'><div class='val-main'>{shares:,} 股</div><div class='val-label'>約 {shares/1000:.1f} 張</div></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='padding-top:10px;color:#cbd5e1;font-size:0.9rem'>—</div>", unsafe_allow_html=True)

        with c5:
            btn_col1, btn_col2 = st.columns([3, 1])
            with btn_col1:
                if st.button(f"📈 AI 分析", key=f"analyze_{i}", use_container_width=True, type="primary"):
                    st.session_state["selected_symbol"] = stock["symbol"]
                    st.switch_page("pages/1_app_tw.py")
            with btn_col2:
                if st.button("🗑️", key=f"del_{i}", help=f"移除 {stock['symbol']}"):
                    removed = portfolio.pop(i)
                    save_portfolio(portfolio)
                    st.toast(f"✅ 已移除「{removed['symbol']}」")
                    st.rerun()

        st.markdown("<hr class='row-divider'>", unsafe_allow_html=True)

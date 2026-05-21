"""共用商業風格樣式模組 — 所有頁面 import 後呼叫 apply_style() 即可套用"""
import streamlit as st


_CSS = """
<style>
/* ── 背景 ── */
.stApp { background: #f0f4f8; }

/* ── 頁首橫幅 ── */
.page-header {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 55%, #1d4ed8 100%);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 22px;
    box-shadow: 0 8px 32px rgba(15,23,42,0.25);
    display: flex;
    align-items: center;
    gap: 20px;
}
.page-header-icon { font-size: 2.8rem; line-height: 1; }
.page-header h1 {
    margin: 0 0 5px;
    color: #ffffff;
    font-size: 1.75rem;
    font-weight: 800;
    letter-spacing: -0.3px;
}
.page-header p { margin: 0; color: #93c5fd; font-size: 0.86rem; }

/* ── 白色卡片容器 ── */
.card {
    background: #ffffff;
    border-radius: 12px;
    padding: 22px 24px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.07);
    border: 1px solid #e2e8f0;
    margin-bottom: 16px;
}

/* ── 統計卡片 ── */
.stat-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 20px 22px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.07);
    border-top: 4px solid #2563eb;
    height: 100%;
}
.stat-card.c-blue   { border-color: #2563eb; }
.stat-card.c-green  { border-color: #16a34a; }
.stat-card.c-purple { border-color: #7c3aed; }
.stat-card.c-amber  { border-color: #d97706; }
.stat-label { color: #64748b; font-size: 0.74rem; font-weight: 700;
              text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 8px; }
.stat-value { color: #0f172a; font-size: 1.65rem; font-weight: 800; }
.stat-sub   { color: #94a3b8; font-size: 0.77rem; margin-top: 4px; }

/* ── 小節標題線 ── */
.section-title {
    font-size: 0.93rem;
    font-weight: 700;
    color: #1e293b;
    margin: 20px 0 8px;
    padding-left: 10px;
    border-left: 3px solid #2563eb;
}

/* ── 表格標題列 ── */
.table-header {
    background: #1e293b;
    border-radius: 10px 10px 0 0;
    padding: 11px 16px;
    margin-bottom: 2px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.table-header span { color: #94a3b8; font-size: 0.77rem; font-weight: 700;
                     text-transform: uppercase; letter-spacing: 0.07em; }
.table-header .th-badge {
    background: #2563eb;
    color: #fff;
    border-radius: 20px;
    padding: 1px 10px;
    font-size: 0.74rem;
    font-weight: 700;
    margin-left: auto;
}

/* ── 欄標題 ── */
.col-hdr {
    color: #94a3b8;
    font-size: 0.71rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 10px 0 4px;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 6px;
}

/* ── 代碼徽章 ── */
.sym-badge {
    display: inline-block;
    background: #dbeafe;
    color: #1d4ed8;
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 1.1rem;
    font-weight: 800;
    letter-spacing: 1px;
}

/* ── 數值欄 ── */
.val-main  { color: #0f172a; font-size: 0.95rem; font-weight: 700; }
.val-label { color: #94a3b8; font-size: 0.71rem; margin-top: 2px; }
.val-pos   { color: #16a34a; font-weight: 700; }
.val-neg   { color: #dc2626; font-weight: 700; }

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
.empty-state p  { color: #94a3b8; font-size: 0.87rem; }

/* ── 表單容器 ── */
div[data-testid="stForm"] {
    background: #ffffff;
    border-radius: 12px;
    padding: 20px 20px 12px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.07);
    border: 1px solid #e2e8f0;
}

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

/* ── 次要 / 危險按鈕 ── */
.stButton > button[kind="secondary"] {
    border-radius: 8px !important;
    transition: all 0.18s ease !important;
}

/* ── 側邊欄美化 ── */
section[data-testid="stSidebar"] {
    background: #1e293b !important;
}
section[data-testid="stSidebar"] * {
    color: #e2e8f0 !important;
}
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stNumberInput input,
section[data-testid="stSidebar"] .stSelectbox select,
section[data-testid="stSidebar"] .stDateInput input {
    background: #0f172a !important;
    border-color: #334155 !important;
    color: #f1f5f9 !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
}
section[data-testid="stSidebar"] hr {
    border-color: #334155 !important;
}

/* ── 隱藏 Streamlit 預設頁尾裝飾 ── */
#MainMenu, footer { visibility: hidden; }
div[data-testid="stDecoration"] { display: none; }
div[data-testid="stSidebarNav"] { display: none; }
</style>
"""


def apply_style():
    """注入全域商業風格 CSS，應在 st.set_page_config 之後立即呼叫。"""
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(icon: str, title: str, subtitle: str = ""):
    """渲染深藍漸層頁首橫幅。"""
    st.markdown(f"""
<div class="page-header">
    <div class="page-header-icon">{icon}</div>
    <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
    </div>
</div>
""", unsafe_allow_html=True)


def render_global_navigation(current_page: str) -> None:
    """Render the shared sidebar navigation used across all pages."""
    nav_items = [
        ("inventory", "💼 庫存股總覽", "Inventory.py"),
        ("app_tw", "📊 AI 台股分析", "pages/1_app_tw.py"),
        ("analysis_history", "🕘 分析歷史", "pages/2_analysis_history.py"),
        ("growth_screener", "📈 成長股篩選", "pages/3_growth_screener.py"),
        ("chip_screener", "🏦 外資籌碼重壓", "pages/4_chip_screener.py"),
        ("bottom_screener", "🌱 底部剛起漲", "pages/5_bottom_screener.py"),
        ("trade_review", "AI 進出場分析", "pages/6_trade_review.py"),
    ]

    labels = {
        "inventory": "💼 庫存股管理",
        "app_tw": "📊 AI 台股分析",
        "analysis_history": "🕘 分析歷史",
        "growth_screener": "📈 成長股篩選",
        "chip_screener": "🏦 外資籌碼重壓",
        "bottom_screener": "🌱 底部剛起漲",
        "trade_review": "AI 進出場分析",
    }

    st.header("功能導覽")
    st.caption("這裡是主入口，可直接切換到分析、歷史與各種選股頁。")

    for page_key, label, target in nav_items:
        is_current = current_page == page_key
        if st.button(
            label,
            use_container_width=True,
            type="primary" if is_current else "secondary",
            key=f"nav_{page_key}",
            disabled=is_current,
        ):
            st.switch_page(target)

    st.markdown("---")
    st.caption(f"目前頁面：{labels.get(current_page, current_page)}")

"""Shared visual styling and sidebar navigation helpers."""
import streamlit as st


_CSS = """
<style>
:root {
    --bg-app: #f3f6f8;
    --bg-surface: #ffffff;
    --bg-sidebar: #1f2d3d;
    --bg-sidebar-input: #132033;
    --bg-header-start: #102033;
    --bg-header-mid: #1d3f62;
    --bg-header-end: #1f5fd6;
    --text-primary: #132033;
    --text-secondary: #516173;
    --text-muted: #8a99ab;
    --text-on-dark: #eef4fb;
    --text-on-header: #ffffff;
    --accent-primary: #2563eb;
    --accent-primary-soft: #dbeafe;
    --accent-positive: #18804b;
    --accent-positive-soft: #dcfce7;
    --accent-risk: #d92d20;
    --accent-risk-soft: #fee2e2;
    --accent-warn: #c77700;
    --accent-neutral: #5b6b7c;
    --border-default: #d9e2ec;
    --shadow-soft: 0 2px 10px rgba(15, 23, 42, 0.08);
    --shadow-hero: 0 8px 32px rgba(15, 23, 42, 0.24);
}

.stApp { background: var(--bg-app); }

.page-header,
.inv-header {
    background: linear-gradient(135deg, var(--bg-header-start) 0%, var(--bg-header-mid) 55%, var(--bg-header-end) 100%);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 22px;
    box-shadow: var(--shadow-hero);
    display: flex;
    align-items: center;
    gap: 20px;
}
.page-header-icon,
.inv-header-icon { font-size: 2.8rem; line-height: 1; }
.page-header h1,
.inv-header h1 {
    margin: 0 0 5px;
    color: var(--text-on-header);
    font-size: 1.75rem;
    font-weight: 800;
    letter-spacing: -0.3px;
}
.page-header p,
.inv-header p { margin: 0; color: #bfdbfe; font-size: 0.86rem; }

.card {
    background: var(--bg-surface);
    border-radius: 12px;
    padding: 22px 24px;
    box-shadow: var(--shadow-soft);
    border: 1px solid var(--border-default);
    margin-bottom: 16px;
}

.stat-card {
    background: var(--bg-surface);
    border-radius: 12px;
    padding: 20px 22px;
    box-shadow: var(--shadow-soft);
    border-top: 4px solid var(--accent-primary);
    height: 100%;
}
.stat-card.c-blue   { border-color: var(--accent-primary); }
.stat-card.c-green  { border-color: var(--accent-positive); }
.stat-card.c-purple { border-color: #7c3aed; }
.stat-card.c-red    { border-color: var(--accent-risk); }
.stat-card.c-amber  { border-color: var(--accent-warn); }
.stat-card.c-slate  { border-color: var(--accent-neutral); }
.stat-label {
    color: var(--text-secondary);
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 8px;
}
.stat-value { color: var(--text-primary); font-size: 1.65rem; font-weight: 800; }
.stat-sub   { color: var(--text-muted); font-size: 0.77rem; margin-top: 4px; }
.stat-value.pos { color: var(--accent-risk); }
.stat-value.neg { color: var(--accent-positive); }

.section-title,
.form-section-title {
    font-size: 0.93rem;
    font-weight: 700;
    color: var(--text-primary);
    margin: 20px 0 8px;
    padding-left: 10px;
    border-left: 3px solid var(--accent-primary);
}

.status-badge {
    display: inline-block;
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 0.72rem;
    font-weight: 800;
}
.status-badge.holding { background: var(--accent-risk-soft); color: #b42318; }
.status-badge.watch { background: var(--accent-primary-soft); color: #0b5ed7; }

.table-header,
.list-header {
    background: var(--bg-sidebar);
    border-radius: 10px 10px 0 0;
    padding: 11px 16px;
    margin-bottom: 2px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.table-header span,
.list-header span {
    color: var(--text-muted);
    font-size: 0.77rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
.table-header .th-badge,
.list-header .lh-count {
    background: var(--accent-primary);
    color: var(--text-on-header);
    border-radius: 20px;
    padding: 1px 10px;
    font-size: 0.74rem;
    font-weight: 700;
    margin-left: auto;
}

.col-hdr {
    color: var(--text-muted);
    font-size: 0.71rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 10px 0 4px;
    border-bottom: 1px solid var(--border-default);
    margin-bottom: 6px;
}

.sym-badge {
    display: inline-block;
    background: var(--accent-primary-soft);
    color: var(--bg-header-end);
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 1.1rem;
    font-weight: 800;
    letter-spacing: 1px;
}
.stock-name-text {
    color: var(--text-secondary);
    font-size: 0.92rem;
    font-weight: 600;
    margin-top: 4px;
}

.val-main  { color: var(--text-primary); font-size: 0.95rem; font-weight: 700; }
.val-label { color: var(--text-muted); font-size: 0.71rem; margin-top: 2px; }
.val-pos   { color: var(--accent-positive); font-weight: 700; }
.val-neg   { color: var(--accent-risk); font-weight: 700; }

.row-divider {
    border: none;
    border-top: 1px solid #edf2f7;
    margin: 4px 0;
}

.empty-state {
    text-align: center;
    padding: 64px 20px;
    background: var(--bg-surface);
    border-radius: 12px;
    box-shadow: var(--shadow-soft);
}
.empty-state .es-icon { font-size: 3.5rem; }
.empty-state h3 { color: var(--accent-neutral); margin: 14px 0 6px; font-size: 1.1rem; }
.empty-state p  { color: var(--text-muted); font-size: 0.87rem; }

div[data-testid="stForm"] {
    background: var(--bg-surface);
    border-radius: 12px;
    padding: 20px 20px 12px;
    box-shadow: var(--shadow-soft);
    border: 1px solid var(--border-default);
}

div[data-testid="stDataFrame"] {
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: 10px;
    box-shadow: var(--shadow-soft);
    overflow: hidden;
}
div[data-testid="stDataFrame"] [role="columnheader"],
div[data-testid="stDataFrame"] [data-testid="stTableStyledTable"] thead th {
    background: #edf4fb !important;
    color: var(--text-primary) !important;
    font-weight: 800 !important;
}
div[data-testid="stDataFrame"] [role="gridcell"],
div[data-testid="stDataFrame"] [role="columnheader"] {
    border-color: #e7edf4 !important;
}
div[data-testid="stDataFrame"] [role="gridcell"] {
    color: var(--text-primary) !important;
}
div[data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] {
    background: #f8fbff !important;
}

div[data-testid="stAlert"] {
    border-radius: 10px !important;
    border: 1px solid var(--border-default) !important;
    box-shadow: var(--shadow-soft);
}
div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] {
    font-size: 0.9rem;
    line-height: 1.55;
}

details[data-testid="stExpander"] {
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: 10px;
    box-shadow: var(--shadow-soft);
    overflow: hidden;
}
details[data-testid="stExpander"] summary {
    font-weight: 700;
    color: var(--text-primary);
}

div[data-testid="stTabs"] button {
    font-weight: 700;
}
div[data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--accent-primary) !important;
}

.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--bg-header-end), #4f8df7) !important;
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

.stButton > button[kind="secondary"] {
    border-radius: 8px !important;
    transition: all 0.18s ease !important;
}

section[data-testid="stSidebar"] {
    background: var(--bg-sidebar) !important;
}
section[data-testid="stSidebar"] * {
    color: var(--text-on-dark) !important;
}
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stNumberInput input,
section[data-testid="stSidebar"] .stSelectbox select,
section[data-testid="stSidebar"] .stDateInput input {
    background: var(--bg-sidebar-input) !important;
    border-color: #3a4b5d !important;
    color: var(--text-on-dark) !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: var(--text-on-header) !important;
}
section[data-testid="stSidebar"] hr {
    border-color: #3a4b5d !important;
}

section[data-testid="stSidebar"] div[data-testid="stButton"] button,
section[data-testid="stSidebar"] .stButton > button {
    background: #32465c !important;
    border: 1px solid #52667d !important;
    color: #f8fafc !important;
    opacity: 1 !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button *,
section[data-testid="stSidebar"] .stButton > button * {
    color: #f8fafc !important;
    opacity: 1 !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"],
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: #2f7df6 !important;
    border: 1px solid #8bbcff !important;
    color: var(--text-on-header) !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"] *,
section[data-testid="stSidebar"] .stButton > button[kind="primary"] * {
    color: var(--text-on-header) !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button:disabled,
section[data-testid="stSidebar"] .stButton > button:disabled {
    opacity: 1 !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover,
section[data-testid="stSidebar"] .stButton > button:hover {
    background: #40566f !important;
    border-color: #6f86a0 !important;
    color: #ffffff !important;
}

#MainMenu, footer { visibility: hidden; }
div[data-testid="stDecoration"] { display: none; }
div[data-testid="stSidebarNav"] { display: none; }
</style>
"""


def apply_style():
    """Inject the shared app CSS after st.set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(icon: str, title: str, subtitle: str = ""):
    """Render the shared page header banner."""
    st.markdown(
        f"""
<div class="page-header">
    <div class="page-header-icon">{icon}</div>
    <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
    </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_global_navigation(current_page: str) -> None:
    """Render the shared sidebar navigation used across all pages."""
    nav_items = [
        ("inventory", "💼 庫存股總覽", "Inventory.py"),
        ("app_tw", "📊 AI 台股分析", "pages/1_app_tw.py"),
        ("analysis_history", "🕘 分析歷史", "pages/2_analysis_history.py"),
        ("growth_screener", "📈 成長股篩選", "pages/3_growth_screener.py"),
        ("chip_screener", "🏦 外資籌碼重壓", "pages/4_chip_screener.py"),
        ("bottom_screener", "🌱 底部剛起漲", "pages/5_bottom_screener.py"),
    ]

    labels = {
        "inventory": "💼 庫存股管理",
        "app_tw": "📊 AI 台股分析",
        "analysis_history": "🕘 分析歷史",
        "growth_screener": "📈 成長股篩選",
        "chip_screener": "🏦 外資籌碼重壓",
        "bottom_screener": "🌱 底部剛起漲",
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

"""Shared visual styling and sidebar navigation helpers."""
import html

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

.meta-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin: 6px 0 18px;
}
.meta-chip {
    background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
    border: 1px solid var(--border-default);
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: var(--shadow-soft);
}
.meta-chip-label {
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}
.meta-chip-value {
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 800;
    line-height: 1.3;
}
.meta-chip-sub {
    color: var(--text-secondary);
    font-size: 0.78rem;
    margin-top: 4px;
}
.meta-chip-value.ok { color: var(--accent-positive); }
.meta-chip-value.warn { color: var(--accent-warn); }

.panel-card {
    background: var(--bg-surface);
    border-radius: 14px;
    padding: 18px 20px;
    box-shadow: var(--shadow-soft);
    border: 1px solid var(--border-default);
    margin-bottom: 14px;
}
.panel-title {
    color: var(--text-primary);
    font-size: 0.95rem;
    font-weight: 800;
    margin-bottom: 6px;
}
.panel-body {
    color: var(--text-secondary);
    font-size: 0.84rem;
    line-height: 1.55;
}
.filter-toolbar {
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: 14px;
    padding: 14px 16px 8px;
    box-shadow: var(--shadow-soft);
    margin-bottom: 14px;
}
.filter-toolbar-title {
    color: var(--text-primary);
    font-size: 0.92rem;
    font-weight: 800;
    margin-bottom: 8px;
}

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

@media (max-width: 900px) {
    .meta-strip {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

div[data-testid="stSelectbox"] label p {
    font-weight: 700 !important;
    color: var(--text-primary) !important;
}
div[data-testid="stSelectbox"] > div[data-baseweb="select"] > div {
    border: 2px solid #7fb0ff !important;
    border-radius: 10px !important;
    background: #ffffff !important;
    box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.08) !important;
    transition: border-color 0.18s ease, box-shadow 0.18s ease !important;
}
div[data-testid="stSelectbox"] > div[data-baseweb="select"] > div:hover,
div[data-testid="stSelectbox"] > div[data-baseweb="select"] > div:focus-within {
    border-color: var(--accent-primary) !important;
    box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.16) !important;
}

.watchlist-tech-card {
    margin-top: 10px;
    margin-bottom: 14px;
    padding: 12px 14px;
    background: linear-gradient(180deg, #f8fbff 0%, #eef5ff 100%);
    border: 1px solid #bfd6ff;
    border-left: 4px solid var(--accent-primary);
    border-radius: 12px;
    box-shadow: var(--shadow-soft);
}
.watchlist-tech-title {
    font-size: 0.82rem;
    font-weight: 800;
    color: var(--text-primary);
    margin-bottom: 6px;
}
.watchlist-tech-body {
    font-size: 0.92rem;
    color: var(--text-primary);
    line-height: 1.55;
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
section[data-testid="stSidebar"] .stButton > button {
    border-radius: 10px !important;
    font-weight: 700 !important;
    transition: all 0.18s ease !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--accent-primary), #4f8df7) !important;
    border: 1px solid rgba(147, 197, 253, 0.45) !important;
    color: var(--text-on-header) !important;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.28) !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #1d4ed8, #60a5fa) !important;
    border-color: rgba(191, 219, 254, 0.8) !important;
    color: var(--text-on-header) !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    background: linear-gradient(135deg, rgba(37, 99, 235, 0.78), rgba(79, 141, 247, 0.92)) !important;
    border: 1px solid rgba(147, 197, 253, 0.38) !important;
    color: var(--text-on-header) !important;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.18) !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
    background: linear-gradient(135deg, rgba(37, 99, 235, 0.92), rgba(96, 165, 250, 1)) !important;
    border-color: rgba(191, 219, 254, 0.8) !important;
    color: var(--text-on-header) !important;
}
section[data-testid="stSidebar"] hr {
    border-color: #3a4b5d !important;
}

.sidebar-panel {
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.42) 0%, rgba(30, 41, 59, 0.58) 100%);
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-radius: 14px;
    padding: 14px 14px 12px;
    margin: 10px 0 12px;
}
.sidebar-panel-title {
    color: #f8fafc;
    font-size: 0.82rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    margin-bottom: 8px;
}
.sidebar-panel-body {
    color: #cbd5e1;
    font-size: 0.78rem;
    line-height: 1.55;
}
.sidebar-panel-body strong {
    color: #ffffff;
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


def _escape(value) -> str:
    return html.escape(str(value), quote=True)


def render_section_title(title: str) -> None:
    """Render the shared section title used above tables and controls."""
    st.markdown(
        f"""<div class="form-section-title">{_escape(title)}</div>""",
        unsafe_allow_html=True,
    )


def render_list_header(title: str, count_text: str = "") -> None:
    """Render a shared dark list/table header with an optional count badge."""
    badge_html = (
        f"""<span class="lh-count">{_escape(count_text)}</span>"""
        if count_text
        else ""
    )
    st.markdown(
        f"""
<div class="list-header">
<span>{_escape(title)}</span>
{badge_html}
</div>
""",
        unsafe_allow_html=True,
    )


def render_empty_state(icon: str, title: str, body: str) -> None:
    """Render a shared empty-state block."""
    st.markdown(
        f"""
<div class="empty-state">
<div class="es-icon">{_escape(icon)}</div>
<h3>{_escape(title)}</h3>
<p>{_escape(body)}</p>
</div>
""",
        unsafe_allow_html=True,
    )


def render_panel(title: str, body_html: str) -> None:
    """Render a compact helper panel. body_html may contain simple inline HTML."""
    st.markdown(
        f"""
<div class="panel-card">
<div class="panel-title">{_escape(title)}</div>
<div class="panel-body">{body_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_meta_strip(items: list[dict]) -> None:
    """Render the shared top-of-page metadata strip."""
    chips = []
    for item in items:
        label = _escape(item.get("label", ""))
        value = _escape(item.get("value", ""))
        sub = _escape(item.get("sub", ""))
        value_class = _escape(item.get("value_class", ""))
        chips.append(
            f"""<div class="meta-chip">
<div class="meta-chip-label">{label}</div>
<div class="meta-chip-value {value_class}">{value}</div>
<div class="meta-chip-sub">{sub}</div>
</div>"""
        )
    st.markdown(
        f"""
<div class="meta-strip">
{''.join(chips)}
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

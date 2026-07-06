import streamlit as st
from datetime import datetime
import html
import re

import pandas as pd
import plotly.express as px

from data_layer.app_common import configure_runtime, ensure_analysis_dir
from data_layer.data_diagnostics import (
    fetch_json_with_diagnostic,
    make_partial_diagnostic,
)
from data_layer.market_api import fetch_json_tpex, fetch_latest_twse_price_rows
from data_layer.time_utils import taipei_date_string
from data_layer.portfolio_store import (
    PortfolioStoreConnectionError,
    create_portfolio_item,
    delete_portfolio_item,
    get_default_family_id,
    get_google_sheet_edit_url,
    get_store_status,
    list_family_ids,
    load_portfolio as load_portfolio_items,
    update_portfolio_item as update_portfolio_record,
)
from render_layer.diagnostics import render_data_diagnostics
from render_layer.style import (
    apply_style,
    render_empty_state,
    render_global_navigation,
    render_list_header,
    render_meta_strip,
    render_panel,
    render_section_title,
)

configure_runtime()

BROKER_FEE_RATE = 0.001425
STOCK_SELL_TAX_RATE = 0.003
URL_TPEX_PRICE = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ANALYSIS_DIR = ensure_analysis_dir()


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
        return taipei_date_string()
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
def fetch_market_snapshot() -> tuple[dict, list[str], list[dict]]:
    snapshot: dict[str, dict] = {}
    errors: list[str] = []
    diagnostics = []

    raw_twse, diag_twse = fetch_json_with_diagnostic(fetch_latest_twse_price_rows, "", "TWSE 行情快照")
    diagnostics.append(diag_twse.to_dict())
    if raw_twse:
        try:
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
                            "vol_lot": (_parse_market_number(row.get("TradeVolume")) or 0) / 1000,
                            "price_date": twse_date,
                        }
        except Exception as exc:
            errors.append(f"TWSE parse failed: {type(exc).__name__}")
    else:
        errors.append("TWSE fetch failed")

    raw_tpex, diag_tpex = fetch_json_with_diagnostic(fetch_json_tpex, URL_TPEX_PRICE, "TPEX 行情快照")
    diagnostics.append(diag_tpex.to_dict())
    if raw_tpex:
        try:
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
                            "vol_lot": (_parse_market_number(row.get("TradingShares")) or 0) / 1000,
                            "price_date": tpex_date,
                        }
        except Exception as exc:
            errors.append(f"TPEX parse failed: {type(exc).__name__}")
    else:
        errors.append("TPEX fetch failed")

    return snapshot, errors, diagnostics


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

.today-dashboard {
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: 14px;
    padding: 18px 20px;
    box-shadow: var(--shadow-soft);
    margin: 18px 0 16px;
}
.today-dashboard-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 14px;
    margin-bottom: 14px;
}
.today-dashboard-title {
    color: var(--text-primary);
    font-size: 1.08rem;
    font-weight: 900;
    line-height: 1.3;
}
.today-dashboard-sub {
    color: var(--text-secondary);
    font-size: 0.8rem;
    margin-top: 3px;
}
.today-dashboard-date {
    color: var(--text-muted);
    font-size: 0.76rem;
    font-weight: 800;
    white-space: nowrap;
}
.today-dashboard-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
}
.today-dashboard-tile {
    background: #f8fbff;
    border: 1px solid #e4edf8;
    border-radius: 10px;
    padding: 12px 14px;
    min-width: 0;
}
.today-dashboard-label {
    color: var(--text-muted);
    font-size: 0.7rem;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 6px;
}
.today-dashboard-value {
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 900;
    line-height: 1.3;
    overflow-wrap: anywhere;
}
.today-dashboard-value.pos { color: var(--accent-risk); }
.today-dashboard-value.neg { color: var(--accent-positive); }
.today-dashboard-note {
    color: var(--text-secondary);
    font-size: 0.75rem;
    line-height: 1.45;
    margin-top: 5px;
}
.today-dashboard-actions {
    margin-top: 12px;
}
.today-dashboard-alerts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    margin-top: 12px;
}
.today-dashboard-alert {
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 0.8rem;
    line-height: 1.45;
    border: 1px solid;
}
.today-dashboard-alert.warn {
    background: #fff8eb;
    border-color: #f3c36d;
    color: #7a4a00;
}
.today-dashboard-alert.ok {
    background: #effaf3;
    border-color: #a9dfbf;
    color: #14623b;
}

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

@media (max-width: 768px) {
    .inv-header {
        padding: 16px 14px;
        border-radius: 12px;
        gap: 12px;
        margin-bottom: 14px;
    }
    .inv-header-icon { font-size: 2rem; }
    .inv-header h1 {
        font-size: 1.18rem;
        margin-bottom: 2px;
        letter-spacing: 0;
    }
    .inv-header p { font-size: 0.77rem; line-height: 1.45; }
    .stat-card { padding: 14px 14px; }
    .stat-value { font-size: 1.2rem; }
    .today-dashboard {
        padding: 14px;
        margin: 14px 0;
    }
    .today-dashboard-head {
        display: block;
    }
    .today-dashboard-date {
        margin-top: 4px;
        white-space: normal;
    }
    .today-dashboard-grid,
    .today-dashboard-alerts {
        grid-template-columns: 1fr;
    }
    .today-dashboard-title {
        font-size: 1rem;
    }
    .today-dashboard-sub,
    .today-dashboard-note,
    .today-dashboard-alert {
        font-size: 0.76rem;
    }
    .today-dashboard-tile {
        padding: 11px 12px;
    }
    .today-dashboard-value {
        font-size: 0.98rem;
    }
    .sym-badge {
        font-size: 0.96rem;
        padding: 3px 9px;
        letter-spacing: 0;
    }
}

.mobile-card-list { display: none; }

@media (max-width: 768px) {
    .mobile-card-list {
        display: grid;
        gap: 10px;
        margin: 8px 0 12px;
    }
    .mobile-stock-card {
        background: #ffffff;
        border: 1px solid var(--border-default);
        border-radius: 10px;
        padding: 12px;
        box-shadow: var(--shadow-soft);
    }
    .mobile-stock-top {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 10px;
        margin-bottom: 10px;
    }
    .mobile-stock-symbol {
        color: var(--bg-header-end);
        font-size: 1.05rem;
        font-weight: 900;
        line-height: 1.2;
    }
    .mobile-stock-name {
        color: var(--text-secondary);
        font-size: 0.78rem;
        font-weight: 700;
        margin-top: 2px;
    }
    .mobile-stock-badge {
        border-radius: 999px;
        padding: 3px 8px;
        font-size: 0.72rem;
        font-weight: 800;
        white-space: nowrap;
    }
    .mobile-stock-badge.holding {
        background: var(--accent-risk-soft);
        color: #b42318;
    }
    .mobile-stock-badge.watch {
        background: var(--accent-primary-soft);
        color: #0b5ed7;
    }
    .mobile-stock-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
    }
    .mobile-stock-cell {
        background: #f8fbff;
        border: 1px solid #e4edf8;
        border-radius: 8px;
        padding: 8px;
        min-width: 0;
    }
    .mobile-stock-label {
        color: var(--text-muted);
        font-size: 0.68rem;
        font-weight: 800;
        margin-bottom: 3px;
    }
    .mobile-stock-value {
        color: var(--text-primary);
        font-size: 0.9rem;
        font-weight: 800;
        overflow-wrap: anywhere;
    }
    .mobile-stock-value.pos { color: var(--accent-risk); }
    .mobile-stock-value.neg { color: var(--accent-positive); }
    .manage-stock-index {
        color: var(--text-muted);
        font-size: 0.72rem;
        font-weight: 800;
        margin-bottom: 4px;
    }
    .manage-stock-symbol {
        margin-bottom: 6px;
    }
    .manage-stock-name {
        padding-top: 0 !important;
        color: var(--text-primary) !important;
        font-size: 0.98rem;
        line-height: 1.35;
    }
    .manage-stock-type {
        margin-top: 8px;
    }
    .js-plotly-plot .plotly text {
        fill: var(--text-primary) !important;
        opacity: 1 !important;
    }
    .js-plotly-plot .plotly .xtitle,
    .js-plotly-plot .plotly .ytitle {
        fill: var(--text-primary) !important;
    }
    details[data-testid="stExpander"] {
        margin-top: 10px;
    }
    details[data-testid="stExpander"] div[data-testid="stVerticalBlock"] {
        gap: 0.35rem;
    }
    details[data-testid="stExpander"] div[data-testid="stHorizontalBlock"] {
        align-items: flex-start;
    }
    details[data-testid="stExpander"] .stock-name-text {
        padding-top: 0 !important;
        color: var(--text-primary);
        font-size: 0.98rem;
    }
    details[data-testid="stExpander"] .manage-stock-index {
        display: none;
    }
    details[data-testid="stExpander"] .manage-stock-type {
        margin-bottom: 0.3rem;
    }
    details[data-testid="stExpander"] .status-badge {
        margin-bottom: 2px;
    }
    details[data-testid="stExpander"] div[data-testid="stNumberInput"] {
        margin-bottom: 0.4rem;
    }
    details[data-testid="stExpander"] div[data-testid="stNumberInput"] input {
        background: #ffffff !important;
        color: var(--text-primary) !important;
        border: 1px solid #b8c7d9 !important;
        border-radius: 8px !important;
        min-height: 42px;
    }
    details[data-testid="stExpander"] div[data-testid="stNumberInput"] button {
        background: #f8fbff !important;
        color: var(--text-primary) !important;
        border-color: #cbd5e1 !important;
    }
    details[data-testid="stExpander"] div[data-testid="stButton"] button {
        min-height: 42px;
        width: 100%;
    }
    .col-hdr {
        display: none;
    }
    .row-divider {
        margin: 12px 0;
    }
    div[data-testid="stNumberInput"] input,
    div[data-testid="stTextInput"] input {
        min-height: 42px;
        font-size: 1rem;
    }
    .stButton > button {
        min-height: 42px;
    }
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


def _escape_html(value) -> str:
    return html.escape(str(value), quote=True)


def _mobile_value_class(value) -> str:
    return pnl_class(value)


def _dashboard_stock_label(row: pd.Series | None) -> str:
    if row is None:
        return "—"
    symbol = str(row.get("symbol", "")).strip()
    name = str(row.get("name", "") or "").strip()
    if symbol and name:
        return f"{symbol} {name}"
    return symbol or name or "—"


def _dashboard_tile(label: str, value: str, note: str = "", value_class: str = "") -> str:
    return f"""
<div class="today-dashboard-tile">
  <div class="today-dashboard-label">{_escape_html(label)}</div>
  <div class="today-dashboard-value {_escape_html(value_class)}">{_escape_html(value)}</div>
  <div class="today-dashboard-note">{_escape_html(note)}</div>
</div>"""


def render_today_investment_dashboard(
    holding_df: pd.DataFrame,
    watch_df: pd.DataFrame,
    latest_price_date: str,
    priced_holding_count: int,
    holding_count: int,
    price_coverage_pct: float,
    total_market: float,
    today_pnl,
    unrealized_pnl,
) -> None:
    if holding_df.empty and watch_df.empty:
        st.markdown(
            """
<div class="today-dashboard">
  <div class="today-dashboard-head">
    <div>
      <div class="today-dashboard-title">今日投資儀表板</div>
      <div class="today-dashboard-sub">尚未建立持股或自選股，加入股票後會自動整理今日重點。</div>
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        return

    priced_holdings = holding_df.dropna(subset=["latest_price"]).copy() if not holding_df.empty else pd.DataFrame()
    today_holdings = holding_df.dropna(subset=["today_pnl"]).copy() if not holding_df.empty else pd.DataFrame()
    watch_movers = watch_df.dropna(subset=["today_return"]).copy() if not watch_df.empty else pd.DataFrame()

    top_position = None
    if not priced_holdings.empty and priced_holdings["market_value"].notna().any():
        top_position = priced_holdings.sort_values("market_value", ascending=False).iloc[0]
    best_today = today_holdings.sort_values("today_pnl", ascending=False).iloc[0] if not today_holdings.empty else None
    worst_today = today_holdings.sort_values("today_pnl", ascending=True).iloc[0] if not today_holdings.empty else None
    top_watch = watch_movers.sort_values("today_return", ascending=False).iloc[0] if not watch_movers.empty else None

    today_note = "持股今日估算損益"
    if today_holdings.empty:
        today_note = "等待最新價與前收資料"

    top_position_note = "尚無可計算市值"
    top_position_value = "—"
    if top_position is not None:
        top_position_value = _dashboard_stock_label(top_position)
        top_position_note = (
            f"{format_money(top_position.get('market_value'))}，"
            f"占比 {top_position.get('position_ratio'):.1f}%"
            if pd.notna(top_position.get("position_ratio"))
            else format_money(top_position.get("market_value"))
        )

    best_note = "尚無今日漲跌資料"
    best_value = "—"
    best_class = ""
    if best_today is not None:
        best_value = _dashboard_stock_label(best_today)
        best_note = f"{format_signed_money(best_today.get('today_pnl'))} / {format_pct(best_today.get('today_return'))}"
        best_class = pnl_class(best_today.get("today_pnl"))

    worst_note = "尚無今日漲跌資料"
    worst_value = "—"
    worst_class = ""
    if worst_today is not None:
        worst_value = _dashboard_stock_label(worst_today)
        worst_note = f"{format_signed_money(worst_today.get('today_pnl'))} / {format_pct(worst_today.get('today_return'))}"
        worst_class = pnl_class(worst_today.get("today_pnl"))

    watch_note = "自選股尚無今日漲跌資料"
    watch_value = "—"
    watch_class = ""
    if top_watch is not None:
        watch_value = _dashboard_stock_label(top_watch)
        watch_note = f"今日漲跌幅 {format_pct(top_watch.get('today_return'))}"
        watch_class = pnl_class(top_watch.get("today_return"))

    tiles = [
        _dashboard_tile("今日損益", format_signed_money(today_pnl), today_note, pnl_class(today_pnl)),
        _dashboard_tile("最大持倉", top_position_value, top_position_note),
        _dashboard_tile("今日最強持股", best_value, best_note, best_class),
        _dashboard_tile("今日最弱持股", worst_value, worst_note, worst_class),
        _dashboard_tile("自選股強勢", watch_value, watch_note, watch_class),
        _dashboard_tile("價格覆蓋", f"{priced_holding_count}/{holding_count}", f"{price_coverage_pct:.0f}% 持股有最新價"),
        _dashboard_tile("未實現損益", format_signed_money(unrealized_pnl), "扣除預估賣出成本後"),
        _dashboard_tile("目前總市值", format_money(total_market), f"{len(priced_holdings)} 檔可計算市值"),
    ]

    alerts = []
    if price_coverage_pct < 99 and holding_count:
        alerts.append(("warn", f"有 {holding_count - priced_holding_count} 檔持股缺最新價，今日損益與市值可能不完整。"))
    if top_position is not None and pd.notna(top_position.get("position_ratio")) and top_position.get("position_ratio") >= 40:
        alerts.append(("warn", f"{_dashboard_stock_label(top_position)} 占投資組合 {top_position.get('position_ratio'):.1f}%，留意單一持股集中度。"))
    down_count = int((today_holdings["today_pnl"] < 0).sum()) if not today_holdings.empty else 0
    if down_count:
        alerts.append(("warn", f"今日有 {down_count} 檔持股下跌，可用下方快速篩選檢查拖累來源。"))
    if not alerts:
        alerts.append(("ok", "今日資料覆蓋完整，持股集中度與下跌檔數未觸發提醒。"))

    alert_html = "".join(
        f"""<div class="today-dashboard-alert {kind}">{_escape_html(message)}</div>"""
        for kind, message in alerts[:4]
    )
    st.markdown(
        f"""
<div class="today-dashboard">
  <div class="today-dashboard-head">
    <div>
      <div class="today-dashboard-title">今日投資儀表板</div>
      <div class="today-dashboard-sub">把持股損益、價格覆蓋、自選股動能與待處理提醒集中在第一屏。</div>
    </div>
    <div class="today-dashboard-date">價格日：{_escape_html(latest_price_date)}</div>
  </div>
  <div class="today-dashboard-grid">
    {''.join(tiles)}
  </div>
  <div class="today-dashboard-alerts">
    {alert_html}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    action_col1, action_col2, action_col3 = st.columns([1, 1, 2])
    with action_col1:
        if st.button("查看今日下跌", use_container_width=True, key="dashboard_filter_down"):
            st.session_state["inventory_scope_mode"] = "持股"
            st.session_state["inventory_quick_filter"] = "今日下跌"
            st.rerun()
    with action_col2:
        if st.button("查看缺最新價", use_container_width=True, key="dashboard_filter_missing"):
            st.session_state["inventory_scope_mode"] = "全部"
            st.session_state["inventory_quick_filter"] = "缺最新價"
            st.rerun()
    with action_col3:
        if top_position is not None and st.button(
            f"分析最大持倉 {_dashboard_stock_label(top_position)}",
            use_container_width=True,
            type="primary",
            key="dashboard_analyze_top_position",
        ):
            st.session_state["selected_symbol"] = str(top_position.get("symbol", ""))
            st.switch_page("pages/1_app_tw.py")


def render_mobile_holding_cards(df: pd.DataFrame) -> None:
    if df.empty:
        return

    cards = []
    for row in df.head(20).to_dict("records"):
        symbol = _escape_html(row.get("symbol", ""))
        name = _escape_html(row.get("name") or "—")
        pnl = row.get("unrealized_pnl")
        today_pnl = row.get("today_pnl")
        cards.append(
            f"""
<div class="mobile-stock-card">
  <div class="mobile-stock-top">
    <div>
      <div class="mobile-stock-symbol">{symbol}</div>
      <div class="mobile-stock-name">{name}</div>
    </div>
    <div class="mobile-stock-badge holding">持股</div>
  </div>
  <div class="mobile-stock-grid">
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">最新價</div>
      <div class="mobile-stock-value">{_escape_html(format_money(row.get("latest_price"), 2))}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">股數</div>
      <div class="mobile-stock-value">{_escape_html(f"{int(row.get('shares')):,} 股" if pd.notna(row.get("shares")) else "—")}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">市值</div>
      <div class="mobile-stock-value">{_escape_html(format_money(row.get("market_value")))}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">未實現損益</div>
      <div class="mobile-stock-value {_mobile_value_class(pnl)}">{_escape_html(format_signed_money(pnl))}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">報酬率</div>
      <div class="mobile-stock-value {_mobile_value_class(row.get("unrealized_return"))}">{_escape_html(format_pct(row.get("unrealized_return")))}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">今日損益</div>
      <div class="mobile-stock-value {_mobile_value_class(today_pnl)}">{_escape_html(format_signed_money(today_pnl))}</div>
    </div>
  </div>
</div>"""
        )

    st.markdown(
        f"""<div class="mobile-card-list">{''.join(cards)}</div>""",
        unsafe_allow_html=True,
    )


def render_mobile_watch_cards(df: pd.DataFrame, analysis_index: dict[str, dict]) -> None:
    if df.empty:
        return

    cards = []
    for row in df.head(20).to_dict("records"):
        symbol_raw = str(row.get("symbol", ""))
        symbol = _escape_html(symbol_raw)
        name = _escape_html(row.get("name") or "—")
        today_return = row.get("today_return")
        analysis_count = analysis_index.get(symbol_raw, {}).get("count", 0)
        cards.append(
            f"""
<div class="mobile-stock-card">
  <div class="mobile-stock-top">
    <div>
      <div class="mobile-stock-symbol">{symbol}</div>
      <div class="mobile-stock-name">{name}</div>
    </div>
    <div class="mobile-stock-badge watch">自選</div>
  </div>
  <div class="mobile-stock-grid">
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">最新價</div>
      <div class="mobile-stock-value">{_escape_html(format_money(row.get("latest_price"), 2))}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">漲跌幅</div>
      <div class="mobile-stock-value {_mobile_value_class(today_return)}">{_escape_html(format_pct(today_return))}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">成交量</div>
      <div class="mobile-stock-value">{_escape_html(f"{row.get('vol_lot'):,.0f} 張" if pd.notna(row.get("vol_lot")) else "—")}</div>
    </div>
    <div class="mobile-stock-cell">
      <div class="mobile-stock-label">分析記錄</div>
      <div class="mobile-stock-value">{_escape_html(f"{int(analysis_count)} 筆" if analysis_count else "—")}</div>
    </div>
  </div>
</div>"""
        )

    st.markdown(
        f"""<div class="mobile-card-list">{''.join(cards)}</div>""",
        unsafe_allow_html=True,
    )


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
        unrealized_pnl = gross_unrealized_pnl
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
            "vol_lot": price_info.get("vol_lot"),
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
            "today_return": (
                (latest_price - previous_price) / previous_price * 100
                if latest_price is not None and previous_price not in (None, 0)
                else None
            ),
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


def filter_inventory_view(
    df: pd.DataFrame,
    search_text: str,
    scope_mode: str,
    quick_filter: str,
    target_type: str,
) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()
    if scope_mode != "全部" and scope_mode != target_type:
        return filtered.iloc[0:0].copy()

    query = search_text.strip().lower()
    if query:
        symbol_match = filtered["symbol"].astype(str).str.lower().str.contains(query, regex=False)
        name_match = filtered["name"].fillna("").astype(str).str.lower().str.contains(query, regex=False)
        filtered = filtered.loc[symbol_match | name_match].copy()

    if quick_filter == "缺最新價":
        filtered = filtered.loc[filtered["latest_price"].isna()].copy()
    elif quick_filter == "虧損中":
        filtered = filtered.loc[filtered["unrealized_pnl"].fillna(0) < 0].copy()
    elif quick_filter == "今日下跌":
        filtered = filtered.loc[filtered["today_pnl"].fillna(0) < 0].copy()
    elif quick_filter == "今日上漲":
        filtered = filtered.loc[filtered["today_pnl"].fillna(0) > 0].copy()

    return filtered


@st.cache_data(ttl=900, show_spinner=False)
def load_analysis_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not ANALYSIS_DIR.exists():
        return index

    for path in ANALYSIS_DIR.glob("*"):
        if path.suffix.lower() not in {".csv", ".md"}:
            continue
        match = re.match(r"^(\d{4,6})_", path.name)
        if not match:
            continue
        stock_id = match.group(1)
        entry = index.setdefault(
            stock_id,
            {"count": 0, "latest_at": "", "has_csv": False, "has_md": False},
        )
        entry["count"] += 1
        latest_at = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
        if latest_at > entry["latest_at"]:
            entry["latest_at"] = latest_at
        if path.suffix.lower() == ".csv":
            entry["has_csv"] = True
        elif path.suffix.lower() == ".md":
            entry["has_md"] = True
    return index


if st.session_state.pop("refresh_market_snapshot", False):
    fetch_market_snapshot.clear()

market_snapshot, market_snapshot_errors, market_snapshot_diagnostics = fetch_market_snapshot()
stock_names = {
    stock_id: info.get("stock_name", "")
    for stock_id, info in market_snapshot.items()
}
analysis_index = load_analysis_index()
store_status = get_store_status()
portfolio_store_error = ""
try:
    known_family_ids = list_family_ids()
except PortfolioStoreConnectionError as exc:
    known_family_ids = []
    portfolio_store_error = str(exc)
store_label = "Google Sheets" if store_status.using_google_sheets else "Local JSON"
with st.sidebar:
    render_global_navigation("inventory")
    st.markdown("---")
    st.markdown(
        f"""
<div class="sidebar-panel">
    <div class="sidebar-panel-title">資料控制台</div>
    <div class="sidebar-panel-body">
        目前來源：<strong>{store_label}</strong><br>
        切換 family_id 後，會重新載入對應家戶的庫存資料。
    </div>
</div>
""",
        unsafe_allow_html=True,
    )
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
try:
    portfolio = load_portfolio_items(family_id)
except PortfolioStoreConnectionError as exc:
    portfolio_store_error = str(exc)
    portfolio = []

if portfolio_store_error and store_status.using_google_sheets:
    st.error(portfolio_store_error)
    st.info("請到 Streamlit secrets 檢查 GOOGLE_SHEETS_PORTFOLIO_SPREADSHEET_ID、GOOGLE_SHEETS_PORTFOLIO_WORKSHEET 與服務帳號是否已加入試算表共用名單。")
    st.stop()

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

latest_price_date = "—"
if not holding_df.empty:
    priced_dates = [
        str(value).strip()
        for value in holding_df["price_date"].dropna().tolist()
        if str(value).strip()
    ]
    if priced_dates:
        latest_price_date = max(priced_dates)

holding_count = len(holding_df)
price_coverage_pct = (
    priced_holding_count / holding_count * 100
    if holding_count
    else 0
)
coverage_class = "ok" if price_coverage_pct >= 99 else "warn"

if market_snapshot_errors:
    render_data_diagnostics(market_snapshot_diagnostics, expanded=True)
    st.warning(
        "行情快照抓取不完整："
        + " | ".join(market_snapshot_errors)
        + "。可先按一次「重新抓取行情」。"
    )
elif missing_price_symbols:
    render_data_diagnostics(
        market_snapshot_diagnostics + [
            make_partial_diagnostic(
                "庫存行情覆蓋",
                "部分持股沒有對到最新價，可能是代碼、上市櫃來源或上游資料延遲造成。",
                records=priced_holding_count,
                sample_ids=missing_price_symbols[:10],
            ).to_dict()
        ],
        expanded=True,
    )
    st.warning(
        f"目前有 {len(missing_price_symbols)} 檔持股沒有對到最新價："
        + ", ".join(missing_price_symbols[:12])
        + "。可先按一次「重新抓取行情」確認是否為暫時性 API 問題。"
    )

with st.sidebar:
    st.markdown(
        f"""
<div class="sidebar-panel">
    <div class="sidebar-panel-title">同步狀態</div>
    <div class="sidebar-panel-body">
        行情覆蓋：<strong>{priced_holding_count}/{holding_count}</strong><br>
        最新價格日：<strong>{latest_price_date}</strong><br>
        {'已偵測到行情缺口，建議重新抓取。' if (market_snapshot_errors or missing_price_symbols) else '目前行情資料看起來完整。'}
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

render_meta_strip(
    [
        {
            "label": "目前家戶",
            "value": family_id,
            "sub": "目前正在查看的 family_id",
        },
        {
            "label": "持股來源",
            "value": store_label,
            "sub": "目前資料後端",
        },
        {
            "label": "行情覆蓋率",
            "value": f"{priced_holding_count}/{holding_count}",
            "sub": f"約 {price_coverage_pct:.0f}% 持股已取得最新價",
            "value_class": coverage_class,
        },
        {
            "label": "最新價格日",
            "value": latest_price_date,
            "sub": "庫存頁目前使用的價格日期",
        },
    ]
)

render_today_investment_dashboard(
    holding_df=holding_df,
    watch_df=watch_df,
    latest_price_date=latest_price_date,
    priced_holding_count=priced_holding_count,
    holding_count=holding_count,
    price_coverage_pct=price_coverage_pct,
    total_market=total_market,
    today_pnl=today_pnl,
    unrealized_pnl=unrealized_pnl,
)

summary_cards = [
    ("兩平成本合計", format_money(total_cost), f"{len(holding_df)} 檔持股", "c-green", ""),
    ("目前總市值", format_money(total_market), f"{priced_holding_count} 檔已取得最新收盤價", "c-blue", ""),
    ("未實現損益", format_money(unrealized_pnl), "最新價 - 損益兩平價，再乘以股數", "c-red" if (unrealized_pnl or 0) >= 0 else "c-green", pnl_class(unrealized_pnl)),
    ("未實現報酬率", format_pct(unrealized_return), "損益 / 兩平成本合計", "c-purple", pnl_class(unrealized_return)),
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
render_section_title("新增自選股 / 持股")

form_col, hint_col = st.columns([2.3, 1.2])
with form_col:
    with st.form("add_stock_form", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns([2, 2, 2, 1.2])
        with col1:
            new_symbol = st.text_input("股票代碼", placeholder="例：2330")
        with col2:
            new_price = st.text_input("損益兩平價（選填）", placeholder="例：241.4")
        with col3:
            new_shares = st.text_input("持有股數（選填）", placeholder="例：1000")
        with col4:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("＋ 新增", use_container_width=True, type="primary")
with hint_col:
    render_panel(
        "輸入小提示",
        """
        只填股票代碼：加入自選股。<br>
        再填成本與股數：直接視為持股。<br>
        如果剛切換 family_id，建議先按一次「重新抓取行情」。
""",
    )

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
        try:
            create_portfolio_item(
                family_id=family_id,
                stock_id=new_symbol,
                avg_cost=price_val,
                shares=shares_val,
                stock_name=stock_names.get(new_symbol, ""),
            )
        except PortfolioStoreConnectionError as exc:
            st.error(str(exc))
        else:
            item_type = "持股" if price_val and shares_val else "自選股"
            st.success(f"✅ 已新增「{new_symbol}」{stock_names.get(new_symbol, '')} 至{item_type}清單")
            st.rerun()

# ── 快速篩選 ──────────────────────────────────────────────────────────────────
render_section_title("快速篩選")
st.markdown('<div class="filter-toolbar-title">快速定位想看的持股與圖表視角</div>', unsafe_allow_html=True)
filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2.2, 1.2, 1.4, 1.4])
with filter_col1:
    search_text = st.text_input("搜尋股票", value="", placeholder="輸入代碼或名稱", key="inventory_search_text")
with filter_col2:
    scope_mode = st.selectbox("清單範圍", ["全部", "持股", "自選股"], key="inventory_scope_mode")
with filter_col3:
    quick_filter = st.selectbox(
        "快速篩選",
        ["全部", "缺最新價", "虧損中", "今日下跌", "今日上漲"],
        key="inventory_quick_filter",
    )
with filter_col4:
    chart_metric = st.selectbox(
        "圖表指標",
        ["持倉比例", "目前市值", "未實現損益", "今日損益", "未實現報酬率"],
        key="inventory_chart_metric",
    )
view_col1, view_col2 = st.columns([1.3, 2.7])
with view_col1:
    holding_view_mode = st.selectbox(
        "持股表檢視",
        ["精簡檢視", "完整檢視"],
        key="inventory_holding_view_mode",
    )

filtered_holding_df = filter_inventory_view(holding_df, search_text, scope_mode, quick_filter, "持股")
filtered_watch_df = filter_inventory_view(watch_df, search_text, scope_mode, quick_filter, "自選股")

# ── 個股圖表 ──────────────────────────────────────────────────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

if not filtered_holding_df.empty and filtered_holding_df["market_value"].notna().any():
    render_section_title("個股圖表")
    st.caption(f"目前圖表指標：{chart_metric}")
    chart_specs = {
        "持倉比例": {
            "column": "position_ratio",
            "label": "持倉比例 (%)",
            "formatter": lambda x: f"{x:.1f}%",
            "signed": False,
        },
        "目前市值": {
            "column": "market_value",
            "label": "目前市值",
            "formatter": lambda x: format_money(x),
            "signed": False,
        },
        "未實現損益": {
            "column": "unrealized_pnl",
            "label": "未實現損益",
            "formatter": lambda x: format_signed_money(x),
            "signed": True,
        },
        "今日損益": {
            "column": "today_pnl",
            "label": "今日損益",
            "formatter": lambda x: format_signed_money(x),
            "signed": True,
        },
        "未實現報酬率": {
            "column": "unrealized_return",
            "label": "未實現報酬率 (%)",
            "formatter": lambda x: format_pct(x),
            "signed": True,
        },
    }
    chart_spec = chart_specs[chart_metric]
    chart_df = filtered_holding_df.dropna(subset=[chart_spec["column"]]).copy()
    chart_df["label"] = chart_df["symbol"] + " " + chart_df["name"].fillna("")
    if not chart_df.empty:
        chart_df = chart_df.sort_values(chart_spec["column"], ascending=True)
        chart_df["metric_text"] = chart_df[chart_spec["column"]].map(chart_spec["formatter"])
        if chart_spec["signed"]:
            chart_df["bar_color"] = chart_df[chart_spec["column"]].apply(
                lambda value: "#d92d20" if pd.notna(value) and value > 0 else "#18804b" if pd.notna(value) and value < 0 else "#5b6b7c"
            )
        else:
            chart_df["bar_color"] = "#2563eb"
        fig = px.bar(
            chart_df,
            x=chart_spec["column"],
            y="label",
            orientation="h",
            text="metric_text",
            color="bar_color",
            color_discrete_map="identity",
            labels={chart_spec["column"]: chart_spec["label"], "label": "股票"},
            height=max(260, 48 * len(chart_df) + 90),
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_layout(
            margin=dict(l=10, r=60, t=24, b=10),
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(color="#132033"),
            showlegend=False,
        )
        fig.update_xaxes(tickfont=dict(color="#132033"), title_font=dict(color="#132033"), gridcolor="#e7edf4")
        fig.update_yaxes(tickfont=dict(color="#132033"), title_font=dict(color="#132033"), gridcolor="#e7edf4")
        st.plotly_chart(fig, use_container_width=True)

# ── 自選股 / 持股清單 ─────────────────────────────────────────────────────────
if not portfolio:
    render_empty_state(
        "📭",
        "庫存清單是空的",
        "在上方輸入股票代碼，按「新增」開始建立自選股或持股清單",
    )
else:
    render_section_title("持股清單")
    render_list_header("持股清單", f"{len(filtered_holding_df)} / {len(holding_df)} 檔")
    st.caption("依目前市值由高到低排序，方便先看資金集中度最高的部位。")

    if holding_df.empty:
        st.info("目前沒有填入成本與股數的持股；只有股票代碼會歸在下方自選股。")
    elif filtered_holding_df.empty:
        st.info("目前篩選條件下沒有符合的持股。")
    else:
        display_holding_df = filtered_holding_df.copy()
        display_holding_df = display_holding_df.sort_values("market_value", ascending=False, na_position="last")
        display_holding_df["股票"] = display_holding_df["symbol"] + " " + display_holding_df["name"].fillna("")
        display_holding_df["損益兩平價"] = display_holding_df["cost_price"]
        display_holding_df["股數"] = display_holding_df["shares"]
        display_holding_df["最新價"] = display_holding_df["latest_price"]
        display_holding_df["兩平成本"] = display_holding_df["invested_cost"]
        display_holding_df["目前市值"] = display_holding_df["market_value"]
        display_holding_df["兩平損益"] = display_holding_df["gross_unrealized_pnl"]
        display_holding_df["賣出手續費"] = display_holding_df["sell_fee"]
        display_holding_df["交易稅"] = display_holding_df["sell_tax"]
        display_holding_df["未實現損益"] = display_holding_df["unrealized_pnl"]
        display_holding_df["未實現報酬率"] = display_holding_df["unrealized_return"]
        display_holding_df["今日損益"] = display_holding_df["today_pnl"]
        display_holding_df["持倉比例"] = display_holding_df["position_ratio"]
        display_holding_df["價格日"] = display_holding_df["price_date"].replace("", "—")
        compact_columns = [
            "股票",
            "損益兩平價",
            "股數",
            "最新價",
            "目前市值",
            "未實現損益",
            "未實現報酬率",
            "今日損益",
            "持倉比例",
            "價格日",
        ]
        full_columns = [
            "股票",
            "損益兩平價",
            "股數",
            "最新價",
            "兩平成本",
            "目前市值",
            "兩平損益",
            "賣出手續費",
            "交易稅",
            "未實現損益",
            "未實現報酬率",
            "今日損益",
            "持倉比例",
            "價格日",
        ]
        display_columns = compact_columns if holding_view_mode == "精簡檢視" else full_columns
        render_mobile_holding_cards(display_holding_df)
        styled_holding_df = display_holding_df[display_columns].style.format({
            "損益兩平價": lambda x: format_money(x, 2),
            "股數": lambda x: f"{int(x):,} 股" if pd.notna(x) else "—",
            "最新價": lambda x: format_money(x, 2),
            "兩平成本": format_money,
            "目前市值": format_money,
            "兩平損益": format_signed_money,
            "賣出手續費": format_money,
            "交易稅": format_money,
            "未實現損益": format_signed_money,
            "未實現報酬率": format_pct,
            "今日損益": format_signed_money,
            "持倉比例": lambda x: f"{x:.2f}%" if pd.notna(x) else "—",
        })
        style_targets = [
            ("兩平損益", "gross_unrealized_pnl"),
            ("未實現損益", "unrealized_pnl"),
            ("未實現報酬率", "unrealized_return"),
            ("今日損益", "today_pnl"),
        ]
        for display_col, source_col in style_targets:
            if display_col in display_columns:
                styled_holding_df = styled_holding_df.apply(
                    lambda col, source_col=source_col: [pnl_color_style(v) for v in display_holding_df[source_col]],
                    subset=[display_col],
                )
        st.dataframe(
            styled_holding_df,
            use_container_width=True,
            hide_index=True,
        )

    render_section_title("自選股清單")
    render_list_header("自選股清單", f"{len(filtered_watch_df)} / {len(watch_df)} 檔")
    st.caption("這裡保留尚未填入成本與股數的觀察名單，方便之後轉成正式持股。")

    if watch_df.empty:
        st.info("目前沒有自選股；新增股票時不填成本與股數，就會放到自選股清單。")
    elif filtered_watch_df.empty:
        st.info("目前篩選條件下沒有符合的自選股。")
    else:
        watch_display = filtered_watch_df.copy()
        watch_display["analysis_count"] = watch_display["symbol"].map(
            lambda symbol: analysis_index.get(str(symbol), {}).get("count", 0)
        )
        watch_display["analysis_latest_at"] = watch_display["symbol"].map(
            lambda symbol: analysis_index.get(str(symbol), {}).get("latest_at", "")
        )
        watch_display["股票"] = watch_display["symbol"] + " " + watch_display["name"].fillna("")
        watch_display["最新價"] = watch_display["latest_price"]
        watch_display["前收"] = watch_display["previous_price"]
        watch_display["漲跌幅"] = watch_display["today_return"]
        watch_display["成交量(張)"] = watch_display["vol_lot"]
        watch_display["分析記錄"] = watch_display["analysis_count"].map(lambda x: f"{int(x)} 筆" if x else "—")
        watch_display["最近分析"] = watch_display["analysis_latest_at"].replace("", "—")
        watch_display["價格日"] = watch_display["price_date"].replace("", "—")
        render_mobile_watch_cards(watch_display, analysis_index)
        watch_view = watch_display[
            ["股票", "最新價", "前收", "漲跌幅", "成交量(張)", "分析記錄", "最近分析", "價格日"]
        ].style.format({
            "最新價": lambda x: format_money(x, 2),
            "前收": lambda x: format_money(x, 2),
            "漲跌幅": format_pct,
            "成交量(張)": lambda x: f"{x:,.0f}" if pd.notna(x) else "—",
        })
        watch_view = watch_view.apply(
            lambda col: [pnl_color_style(v) for v in watch_display["today_return"]],
            subset=["漲跌幅"],
        )
        st.dataframe(watch_view, use_container_width=True, hide_index=True)

    with st.expander("管理持股 / 自選股", expanded=False):
        render_section_title("操作")
        h_info, h_edit, h_action = st.columns([2.8, 2.6, 2.8])
        h_info.markdown('<div class="col-hdr">股票</div>', unsafe_allow_html=True)
        h_edit.markdown('<div class="col-hdr">兩平價 / 股數</div>', unsafe_allow_html=True)
        h_action.markdown('<div class="col-hdr">操作</div>', unsafe_allow_html=True)

        for i, stock in enumerate(portfolio):
            row_id = str(stock.get("row_id", "")).strip()
            symbol = str(stock.get("symbol", ""))
            row_key = row_id or f"{family_id}_{symbol}"
            matched = portfolio_df[portfolio_df["row_id"] == row_id]
            item_type = matched.iloc[0]["type"] if not matched.empty else "自選股"
            name = stock_names.get(symbol, "")
            default_price = _to_float(stock.get("price"))
            default_shares = _to_int(stock.get("shares"))

            c_info, c_edit, c_action = st.columns([2.8, 2.6, 2.8])
            with c_info:
                st.markdown(f"<div class='manage-stock-index'>{i+1}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='manage-stock-symbol'><span class='sym-badge'>{symbol}</span></div>", unsafe_allow_html=True)
                _name_html = name if name else "<span style='color:#cbd5e1'>—</span>"
                st.markdown(f"<div class='stock-name-text manage-stock-name'>{_name_html}</div>", unsafe_allow_html=True)
                badge_class = "holding" if item_type == "持股" else "watch"
                st.markdown(f"<div class='manage-stock-type'><span class='status-badge {badge_class}'>{item_type}</span></div>", unsafe_allow_html=True)
            with c_edit:
                edit_col1, edit_col2 = st.columns(2)
                with edit_col1:
                    edit_price = st.number_input(
                        "成本",
                        min_value=0.0,
                        step=0.1,
                        value=float(default_price or 0.0),
                        key=f"price_{row_key}",
                        label_visibility="collapsed",
                    )
                with edit_col2:
                    edit_shares = st.number_input(
                        "股數",
                        min_value=0,
                        step=1,
                        value=int(default_shares or 0),
                        key=f"shares_{row_key}",
                        label_visibility="collapsed",
                    )
                if st.button("儲存", key=f"save_{row_key}", use_container_width=True):
                    try:
                        update_portfolio_record(
                            row_id=row_id,
                            family_id=family_id,
                            avg_cost=edit_price if edit_price > 0 else None,
                            shares=edit_shares if edit_shares > 0 else None,
                        )
                    except PortfolioStoreConnectionError as exc:
                        st.error(str(exc))
                    else:
                        st.toast(f"已更新「{symbol}」的持股資料")
                        st.rerun()
            with c_action:
                btn_col1, btn_col2 = st.columns([3, 1])
                with btn_col1:
                    if st.button("📈 AI 分析", key=f"analyze_{row_key}", use_container_width=True, type="primary"):
                        st.session_state["selected_symbol"] = symbol
                        st.switch_page("pages/1_app_tw.py")
                with btn_col2:
                    if st.button("🗑️", key=f"del_{row_key}", help=f"移除 {symbol}", use_container_width=True):
                        try:
                            delete_portfolio_item(row_id=row_id, family_id=family_id)
                        except PortfolioStoreConnectionError as exc:
                            st.error(str(exc))
                        else:
                            st.toast(f"✅ 已移除「{symbol}」")
                            st.rerun()

            st.markdown("<hr class='row-divider'>", unsafe_allow_html=True)

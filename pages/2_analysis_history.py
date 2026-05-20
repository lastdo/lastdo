import logging

class _IgnoreBareMode(logging.Filter):
    def filter(self, record):
        return "missing ScriptRunContext" not in record.getMessage()

logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context"
).addFilter(_IgnoreBareMode())

import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime

st.set_page_config(
    page_title="分析記錄",
    page_icon="📂",
    layout="wide",
)

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).parent.parent))
from _style import apply_style, page_header
apply_style()
page_header("📂", "分析記錄", "儲存自 AI 台股趨勢分析系統的技術面資料（CSV）與 AI 報告（Markdown）")

ANALYSIS_DIR = Path(__file__).parent.parent / "analysis"
ANALYSIS_DIR.mkdir(exist_ok=True)

# ── 掃描 analysis 資料夾 ──────────────────────────
csv_files = sorted(ANALYSIS_DIR.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
md_files  = sorted(ANALYSIS_DIR.glob("*.md"),  key=lambda f: f.stat().st_mtime, reverse=True)

all_files = sorted(
    list(csv_files) + list(md_files),
    key=lambda f: f.stat().st_mtime,
    reverse=True,
)

if not all_files:
    st.info("📭 尚無分析記錄。請至「AI 台股趨勢分析系統」按下「儲存到分析記錄」按鈕。")
    st.stop()

# ── 側邊篩選 ──────────────────────────────────────
with st.sidebar:
    st.header("🔍 篩選")
    st.divider()

    file_type = st.radio(
        "檔案類型",
        ["全部", "📊 技術面 CSV", "🤖 AI 報告 MD"],
        index=0,
    )

    keywords = st.text_input("股票代碼 / 名稱篩選", placeholder="例：2330 或 台積電")

    st.markdown("---")
    if st.button("🗑️ 清除所有記錄", type="secondary", use_container_width=True):
        st.session_state["confirm_delete_all"] = True

    if st.session_state.get("confirm_delete_all"):
        st.warning("確定要刪除所有分析記錄嗎？此操作無法復原。")
        c1, c2 = st.columns(2)
        if c1.button("✅ 確定刪除", use_container_width=True):
            for f in all_files:
                f.unlink()
            st.session_state.pop("confirm_delete_all", None)
            st.success("已清除所有記錄")
            st.rerun()
        if c2.button("❌ 取消", use_container_width=True):
            st.session_state.pop("confirm_delete_all", None)
            st.rerun()

# ── 過濾檔案 ──────────────────────────────────────
filtered = all_files
if file_type == "📊 技術面 CSV":
    filtered = [f for f in filtered if f.suffix == ".csv"]
elif file_type == "🤖 AI 報告 MD":
    filtered = [f for f in filtered if f.suffix == ".md"]
if keywords.strip():
    filtered = [f for f in filtered if keywords.strip().lower() in f.name.lower()]

st.subheader(f"共 {len(filtered)} 筆記錄")

if not filtered:
    st.info("沒有符合條件的記錄。")
    st.stop()

# ── 記錄列表 + 線上預覽 ───────────────────────────
for file in filtered:
    mtime = datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    icon  = "📊" if file.suffix == ".csv" else "🤖"
    size_kb = file.stat().st_size / 1024

    with st.expander(f"{icon} {file.name}　　🕐 {mtime}　　📦 {size_kb:.1f} KB"):
        col_dl, col_del = st.columns([5, 1])

        with col_dl:
            data = file.read_bytes()
            mime = "text/csv" if file.suffix == ".csv" else "text/markdown"
            st.download_button(
                label=f"⬇️ 下載 {file.name}",
                data=data,
                file_name=file.name,
                mime=mime,
                key=f"dl_{file.name}",
                use_container_width=True,
            )

        with col_del:
            if st.button("🗑️", key=f"del_{file.name}", help="刪除此記錄"):
                file.unlink()
                st.toast(f"已刪除 {file.name}")
                st.rerun()

        st.markdown("---")

        # 線上預覽
        if file.suffix == ".csv":
            try:
                df = pd.read_csv(file, encoding="utf-8-sig")
                st.dataframe(df, use_container_width=True, height=400)
            except Exception as e:
                st.error(f"無法讀取 CSV：{e}")

        elif file.suffix == ".md":
            try:
                content = file.read_text(encoding="utf-8")
                st.markdown(content)
            except Exception as e:
                st.error(f"無法讀取報告：{e}")

from datetime import datetime

import pandas as pd
import streamlit as st

from _app_common import ensure_analysis_dir
from _export_utils import CSV_ENCODING
from _style import apply_style, page_header, render_global_navigation


st.set_page_config(
    page_title="分析記錄",
    page_icon="📂",
    layout="wide",
)

apply_style()
page_header("📂", "分析記錄", "儲存自 AI 台股趨勢分析系統的技術面資料（CSV）與 AI 報告（Markdown）")

ANALYSIS_DIR = ensure_analysis_dir()

with st.sidebar:
    render_global_navigation("analysis_history")
    st.markdown("---")
    st.header("篩選")
    st.divider()

    file_type = st.radio(
        "檔案類型",
        ["全部", "只看技術面 CSV", "只看 AI 報告 MD"],
        index=0,
    )

    keywords = st.text_input("股票代碼 / 名稱搜尋", placeholder="例如：2330 或 台積電")

    st.markdown("---")
    if st.button("清除全部分析記錄", type="secondary", use_container_width=True):
        st.session_state["confirm_delete_all"] = True

    if st.session_state.get("confirm_delete_all"):
        st.warning("這會刪除目前所有分析記錄檔案，請再次確認。")
        c1, c2 = st.columns(2)
        if c1.button("確認全部刪除", use_container_width=True):
            for file in ANALYSIS_DIR.glob("*"):
                if file.suffix in {".csv", ".md"}:
                    file.unlink()
            st.session_state.pop("confirm_delete_all", None)
            st.success("已清除所有分析記錄。")
            st.rerun()
        if c2.button("取消", use_container_width=True):
            st.session_state.pop("confirm_delete_all", None)
            st.rerun()

csv_files = sorted(ANALYSIS_DIR.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
md_files = sorted(ANALYSIS_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

all_files = sorted(
    list(csv_files) + list(md_files),
    key=lambda f: f.stat().st_mtime,
    reverse=True,
)

if file_type == "只看技術面 CSV":
    filtered = [f for f in all_files if f.suffix == ".csv"]
elif file_type == "只看 AI 報告 MD":
    filtered = [f for f in all_files if f.suffix == ".md"]
else:
    filtered = all_files

if keywords.strip():
    keyword = keywords.strip().lower()
    filtered = [f for f in filtered if keyword in f.name.lower()]

st.subheader(f"共 {len(filtered)} 筆記錄")

if not all_files:
    st.info("尚無分析記錄。請至「AI 台股趨勢分析系統」按下「儲存到分析記錄」按鈕。")
    st.stop()

if not filtered:
    st.info("沒有符合目前篩選條件的分析記錄。")
    st.stop()

for file in filtered:
    mtime = datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    icon = "📈" if file.suffix == ".csv" else "📝"
    size_kb = file.stat().st_size / 1024

    with st.expander(f"{icon} {file.name} · {mtime} · {size_kb:.1f} KB"):
        col_dl, col_del = st.columns([5, 1])

        with col_dl:
            data = file.read_bytes()
            mime = "text/csv" if file.suffix == ".csv" else "text/markdown"
            st.download_button(
                label=f"下載 {file.name}",
                data=data,
                file_name=file.name,
                mime=mime,
                key=f"dl_{file.name}",
                use_container_width=True,
            )

        with col_del:
            if st.button("刪除", key=f"del_{file.name}", help=f"刪除 {file.name}"):
                file.unlink()
                st.toast(f"已刪除 {file.name}")
                st.rerun()

        st.markdown("---")

        if file.suffix == ".csv":
            try:
                df = pd.read_csv(file, encoding=CSV_ENCODING)
                st.dataframe(df, use_container_width=True, height=400)
            except Exception as exc:
                st.error(f"無法讀取 CSV：{exc}")
        else:
            try:
                content = file.read_text(encoding="utf-8")
                st.markdown(content)
            except Exception as exc:
                st.error(f"無法讀取 Markdown：{exc}")

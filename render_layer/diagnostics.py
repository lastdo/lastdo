from __future__ import annotations

from datetime import datetime
import pandas as pd
import streamlit as st

from data_layer.data_diagnostics import (
    STATUS_CACHED,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PARTIAL,
    DataSourceDiagnostic,
    diagnostic_from_dict,
)


STATUS_LABELS = {
    STATUS_COMPLETE: "完整資料",
    STATUS_PARTIAL: "部分資料",
    STATUS_CACHED: "快取資料",
    STATUS_FAILED: "抓取失敗",
}


def render_data_diagnostics(
    diagnostics: list[dict | DataSourceDiagnostic],
    title: str = "資料來源診斷",
    expanded: bool = False,
    cache_age_minutes: int = 10,
) -> None:
    items = [diagnostic_from_dict(item) for item in diagnostics if item]
    if not items:
        return

    now = datetime.now()
    for item in items:
        if item.status != STATUS_COMPLETE or not item.checked_at:
            continue
        try:
            checked_at = datetime.strptime(item.checked_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        age_minutes = (now - checked_at).total_seconds() / 60
        if age_minutes >= cache_age_minutes:
            item.status = STATUS_CACHED
            item.message = f"使用 {item.checked_at} 建立的快取資料，若需最新狀態請重新抓取或清除快取。"

    failed = [item for item in items if item.status == STATUS_FAILED]
    partial = [item for item in items if item.status in {STATUS_PARTIAL, STATUS_CACHED}]

    if failed:
        st.error(f"{title}：有 {len(failed)} 個資料來源抓取失敗，本頁結果不可視為完整。")
    elif partial:
        st.warning(f"{title}：有 {len(partial)} 個資料來源為部分資料或快取狀態，請留意結果完整性。")
    else:
        st.caption(f"{title}：所有資料來源本次狀態正常。")

    rows = []
    for item in items:
        rows.append(
            {
                "資料來源": item.source,
                "狀態": STATUS_LABELS.get(item.status, item.status),
                "筆數": "" if item.records is None else item.records,
                "說明": item.message,
                "細節": item.detail,
                "樣本": "、".join(item.sample_ids[:10]),
                "檢查時間": item.checked_at,
            }
        )

    with st.expander(title, expanded=expanded or bool(failed)):
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

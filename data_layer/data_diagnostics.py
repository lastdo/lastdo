from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable, Iterable


STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_CACHED = "cached"
STATUS_FAILED = "failed"


@dataclass
class DataSourceDiagnostic:
    source: str
    status: str
    message: str
    records: int | None = None
    detail: str = ""
    sample_ids: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        return asdict(self)


def diagnostic_from_dict(item: dict | DataSourceDiagnostic) -> DataSourceDiagnostic:
    if isinstance(item, DataSourceDiagnostic):
        return item
    return DataSourceDiagnostic(
        source=str(item.get("source", "")),
        status=str(item.get("status", STATUS_FAILED)),
        message=str(item.get("message", "")),
        records=item.get("records"),
        detail=str(item.get("detail", "")),
        sample_ids=[str(x) for x in item.get("sample_ids", [])],
        checked_at=str(item.get("checked_at", "")) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def fetch_json_with_diagnostic(
    fetcher: Callable[[str], list],
    url: str,
    source: str,
    empty_message: str = "資料來源回傳空資料，頁面結果可能不完整。",
) -> tuple[list, DataSourceDiagnostic]:
    try:
        data = fetcher(url)
    except Exception as exc:
        return [], DataSourceDiagnostic(
            source=source,
            status=STATUS_FAILED,
            message="抓取失敗，已將本資料源標記為不可用。",
            detail=f"{type(exc).__name__}: {exc}",
            records=0,
        )

    records = len(data) if isinstance(data, list) else 0
    if records == 0:
        return [], DataSourceDiagnostic(
            source=source,
            status=STATUS_PARTIAL,
            message=empty_message,
            records=0,
        )

    return data, DataSourceDiagnostic(
        source=source,
        status=STATUS_COMPLETE,
        message="抓取成功。",
        records=records,
    )


def make_partial_diagnostic(
    source: str,
    message: str,
    records: int | None = None,
    detail: str = "",
    sample_ids: Iterable[object] = (),
) -> DataSourceDiagnostic:
    return DataSourceDiagnostic(
        source=source,
        status=STATUS_PARTIAL,
        message=message,
        records=records,
        detail=detail,
        sample_ids=[str(x) for x in sample_ids],
    )


def make_failed_diagnostic(
    source: str,
    message: str,
    records: int | None = 0,
    detail: str = "",
    sample_ids: Iterable[object] = (),
) -> DataSourceDiagnostic:
    return DataSourceDiagnostic(
        source=source,
        status=STATUS_FAILED,
        message=message,
        records=records,
        detail=detail,
        sample_ids=[str(x) for x in sample_ids],
    )


def make_cached_diagnostic(
    source: str,
    message: str,
    records: int | None = None,
    detail: str = "",
) -> DataSourceDiagnostic:
    return DataSourceDiagnostic(
        source=source,
        status=STATUS_CACHED,
        message=message,
        records=records,
        detail=detail,
    )


def make_finmind_diagnostic(
    source: str,
    status_code,
    message: str,
    records: int | None = None,
    retry_after=None,
    sample_ids: Iterable[object] = (),
) -> DataSourceDiagnostic:
    status = STATUS_COMPLETE if status_code == 200 and (records is None or records > 0) else STATUS_PARTIAL
    text = "抓取成功。" if status == STATUS_COMPLETE else "FinMind 回傳空資料或非 200 狀態，資料可能不完整。"
    if status_code in (402, 403, 429):
        status = STATUS_FAILED
        text = "FinMind 觸發額度、權限或限流，請勿將本次結果視為完整。"
    detail = f"status={status_code}"
    if retry_after not in (None, ""):
        detail += f", retry_after={retry_after}"
    if message:
        detail += f", message={message}"
    return DataSourceDiagnostic(
        source=source,
        status=status,
        message=text,
        records=records,
        detail=detail,
        sample_ids=[str(x) for x in sample_ids],
    )


def has_blocking_diagnostics(items: Iterable[dict | DataSourceDiagnostic]) -> bool:
    return any(diagnostic_from_dict(item).status == STATUS_FAILED for item in items)


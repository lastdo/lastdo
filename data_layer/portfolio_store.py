import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from data_layer.app_common import get_portfolio_file
from data_layer.contracts import PORTFOLIO_ITEM_FIELDS

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:  # pragma: no cover - optional dependency for local fallback
    gspread = None
    Credentials = None


PORTFOLIO_FILE = get_portfolio_file()
WORKSHEET_HEADERS = [
    "row_id",
    "family_id",
    "stock_id",
    "stock_name",
    "avg_cost",
    "shares",
    "note",
    "created_at",
    "updated_at",
    "is_deleted",
]
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _resolve_local_portfolio_source():
    if PORTFOLIO_FILE.exists():
        return PORTFOLIO_FILE

    # Backward compatibility: some local backups were saved with timestamp
    # suffixes like `portfolio.json(20260524)`.
    legacy_candidates = sorted(
        PORTFOLIO_FILE.parent.glob(f"{PORTFOLIO_FILE.name}*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in legacy_candidates:
        if candidate.is_file():
            return candidate
    return PORTFOLIO_FILE


@dataclass
class PortfolioStoreStatus:
    backend: str
    using_google_sheets: bool
    configured: bool
    message: str = ""


def _secrets() -> dict[str, Any]:
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def normalize_portfolio_item(item: dict[str, Any], family_id: str = "") -> dict[str, Any]:
    stock_id = str(item.get("stock_id") or item.get("symbol") or "").strip()
    stock_name = str(item.get("stock_name") or item.get("name") or "").strip()
    note = str(item.get("note") or "").strip()
    normalized = {
        "row_id": str(item.get("row_id") or uuid.uuid4().hex),
        "family_id": str(item.get("family_id") or family_id or "").strip(),
        "symbol": stock_id,
        "stock_id": stock_id,
        "stock_name": stock_name,
        "name": stock_name,
        "price": _to_float(item.get("avg_cost", item.get("price"))),
        "avg_cost": _to_float(item.get("avg_cost", item.get("price"))),
        "shares": _to_int(item.get("shares")),
        "note": note,
        "created_at": str(item.get("created_at") or _utc_now()),
        "updated_at": str(item.get("updated_at") or _utc_now()),
        "is_deleted": _is_truthy(item.get("is_deleted")),
    }
    return {field: normalized[field] for field in PORTFOLIO_ITEM_FIELDS}


def get_default_family_id() -> str:
    secrets = _secrets()
    return str(secrets.get("PORTFOLIO_DEFAULT_FAMILY_ID", "lwh38009")).strip()


def _load_local_portfolio() -> list[dict[str, Any]]:
    source_file = _resolve_local_portfolio_source()
    if not source_file.exists():
        return []

    with open(source_file, "r", encoding="utf-8") as file:
        raw_items = json.load(file)

    normalized_items = [normalize_portfolio_item(item) for item in raw_items]

    # Backfill legacy local portfolio rows so row_id/family metadata stay stable
    # across reruns; otherwise update/delete actions can point at transient ids.
    # Also migrate timestamp-suffixed legacy files back to the canonical
    # `portfolio.json` location so future reads/writes stay consistent.
    if raw_items != normalized_items or source_file != PORTFOLIO_FILE:
        _save_local_portfolio(normalized_items)

    return normalized_items


def _save_local_portfolio(items: list[dict[str, Any]]) -> None:
    payload = []
    for item in items:
        normalized = normalize_portfolio_item(item)
        payload.append(
            {
                "row_id": normalized["row_id"],
                "family_id": normalized["family_id"],
                "symbol": normalized["stock_id"],
                "stock_name": normalized["stock_name"],
                "price": normalized["avg_cost"],
                "shares": normalized["shares"],
                "note": normalized["note"],
                "created_at": normalized["created_at"],
                "updated_at": normalized["updated_at"],
            }
        )

    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _google_sheets_enabled() -> bool:
    secrets = _secrets()
    return _is_truthy(secrets.get("PORTFOLIO_USE_GOOGLE_SHEETS", False))


def get_google_sheet_edit_url() -> str:
    secrets = _secrets()
    spreadsheet_id = str(secrets.get("GOOGLE_SHEETS_PORTFOLIO_SPREADSHEET_ID", "")).strip()
    if not spreadsheet_id:
        return ""
    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    worksheet_gid = str(secrets.get("GOOGLE_SHEETS_PORTFOLIO_WORKSHEET_GID", "")).strip()
    if worksheet_gid.isdigit():
        url = f"{url}#gid={worksheet_gid}"
    return url


def _google_config_available() -> bool:
    secrets = _secrets()
    return bool(
        gspread
        and Credentials
        and secrets.get("GOOGLE_SERVICE_ACCOUNT")
        and secrets.get("GOOGLE_SHEETS_PORTFOLIO_SPREADSHEET_ID")
    )


def get_store_status() -> PortfolioStoreStatus:
    if _google_sheets_enabled() and _google_config_available():
        return PortfolioStoreStatus(
            backend="google_sheets",
            using_google_sheets=True,
            configured=True,
            message="Google Sheets",
        )
    if _google_sheets_enabled():
        return PortfolioStoreStatus(
            backend="local_json",
            using_google_sheets=False,
            configured=False,
            message="Google Sheets secrets or dependencies are missing; using local JSON fallback.",
        )
    return PortfolioStoreStatus(
        backend="local_json",
        using_google_sheets=False,
        configured=True,
        message="Local JSON",
    )


def _get_worksheet():
    secrets = _secrets()
    creds_info = secrets.get("GOOGLE_SERVICE_ACCOUNT")
    spreadsheet_id = str(secrets.get("GOOGLE_SHEETS_PORTFOLIO_SPREADSHEET_ID", "")).strip()
    worksheet_name = str(secrets.get("GOOGLE_SHEETS_PORTFOLIO_WORKSHEET", "holdings")).strip()

    credentials = Credentials.from_service_account_info(creds_info, scopes=GOOGLE_SCOPES)
    client = gspread.authorize(credentials)
    worksheet = client.open_by_key(spreadsheet_id).worksheet(worksheet_name)
    _ensure_headers(worksheet)
    return worksheet


def _ensure_headers(worksheet) -> None:
    current_headers = worksheet.row_values(1)
    if current_headers[: len(WORKSHEET_HEADERS)] != WORKSHEET_HEADERS:
        worksheet.update(values=[WORKSHEET_HEADERS], range_name="A1:J1")


def _sheet_records() -> list[dict[str, Any]]:
    worksheet = _get_worksheet()
    return worksheet.get_all_records(expected_headers=WORKSHEET_HEADERS)


def _sheet_row_values(row: dict[str, Any]) -> list[Any]:
    normalized = normalize_portfolio_item(row)
    return [
        normalized["row_id"],
        normalized["family_id"],
        normalized["stock_id"],
        normalized["stock_name"],
        normalized["avg_cost"] if normalized["avg_cost"] is not None else "",
        normalized["shares"] if normalized["shares"] is not None else "",
        normalized["note"],
        normalized["created_at"],
        normalized["updated_at"],
        "TRUE" if normalized["is_deleted"] else "FALSE",
    ]


def _sheet_row_to_record(row_values: list[Any]) -> dict[str, Any]:
    cells = [str(value) for value in row_values[: len(WORKSHEET_HEADERS)]]
    if len(cells) < len(WORKSHEET_HEADERS):
        cells.extend([""] * (len(WORKSHEET_HEADERS) - len(cells)))
    return {header: cells[idx] for idx, header in enumerate(WORKSHEET_HEADERS)}


def _find_sheet_row(worksheet, row_id: str, family_id: str) -> tuple[int, dict[str, Any]] | None:
    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) < 2:
        return None

    for row_index, row_values in enumerate(all_values[1:], start=2):
        normalized = normalize_portfolio_item(_sheet_row_to_record(row_values))
        if normalized["row_id"] == row_id and normalized["family_id"] == family_id:
            return row_index, normalized
    return None


def _update_sheet_row(worksheet, row_index: int, row: dict[str, Any]) -> None:
    worksheet.update(values=[_sheet_row_values(row)], range_name=f"A{row_index}:J{row_index}")


def _write_sheet_rows(rows: list[dict[str, Any]]) -> None:
    worksheet = _get_worksheet()
    for row in rows:
        worksheet.append_row(_sheet_row_values(row), value_input_option="USER_ENTERED")


def _migrate_local_to_sheet(default_family_id: str) -> None:
    if _sheet_records():
        return

    local_items = _load_local_portfolio()
    if not local_items:
        return

    rows = []
    for item in local_items:
        normalized = normalize_portfolio_item(item, family_id=default_family_id)
        normalized["family_id"] = default_family_id
        rows.append(normalized)
    _write_sheet_rows(rows)


def list_family_ids() -> list[str]:
    if get_store_status().using_google_sheets:
        family_ids = {
            normalize_portfolio_item(row).get("family_id", "").strip()
            for row in _sheet_records()
            if not _is_truthy(row.get("is_deleted"))
        }
        return sorted(family_id for family_id in family_ids if family_id)

    local_items = _load_local_portfolio()
    family_ids = {
        normalize_portfolio_item(item, family_id=get_default_family_id())["family_id"]
        for item in local_items
    }
    return sorted(family_id for family_id in family_ids if family_id)


def load_portfolio(family_id: str) -> list[dict[str, Any]]:
    family_id = family_id.strip()
    if not family_id:
        return []

    if get_store_status().using_google_sheets:
        _migrate_local_to_sheet(family_id)
        rows = []
        for record in _sheet_records():
            normalized = normalize_portfolio_item(record)
            if normalized["family_id"] == family_id and not normalized["is_deleted"]:
                rows.append(normalized)
        rows.sort(key=lambda item: (item["stock_id"], item["created_at"]))
        return rows

    rows = []
    normalized_items = []
    updated = False
    for item in _load_local_portfolio():
        normalized = normalize_portfolio_item(item, family_id=family_id)
        normalized_items.append(normalized)
        if normalized["family_id"] != item.get("family_id", "").strip():
            updated = True
        if normalized["family_id"] == family_id and not normalized["is_deleted"]:
            rows.append(normalized)

    if updated:
        _save_local_portfolio(normalized_items)

    return rows


def create_portfolio_item(
    family_id: str,
    stock_id: str,
    avg_cost=None,
    shares=None,
    stock_name: str = "",
    note: str = "",
) -> dict[str, Any]:
    item = normalize_portfolio_item(
        {
            "family_id": family_id,
            "stock_id": stock_id,
            "stock_name": stock_name,
            "avg_cost": avg_cost,
            "shares": shares,
            "note": note,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "is_deleted": False,
        }
    )

    if get_store_status().using_google_sheets:
        _migrate_local_to_sheet(family_id)
        worksheet = _get_worksheet()
        worksheet.append_row(_sheet_row_values(item), value_input_option="USER_ENTERED")
        return item

    items = _load_local_portfolio()
    items.append(item)
    _save_local_portfolio(items)
    return item


def update_portfolio_item(row_id: str, family_id: str, avg_cost=None, shares=None, note: str | None = None) -> None:
    if get_store_status().using_google_sheets:
        _migrate_local_to_sheet(family_id)
        worksheet = _get_worksheet()
        found = _find_sheet_row(worksheet, row_id=row_id, family_id=family_id)
        if not found:
            raise KeyError(f"Portfolio row not found: {row_id}")
        row_index, normalized = found
        normalized["avg_cost"] = _to_float(avg_cost)
        normalized["price"] = normalized["avg_cost"]
        normalized["shares"] = _to_int(shares)
        if note is not None:
            normalized["note"] = note
        normalized["updated_at"] = _utc_now()
        _update_sheet_row(worksheet, row_index, normalized)
        return

    items = _load_local_portfolio()
    matched = False
    for item in items:
        normalized = normalize_portfolio_item(item, family_id=family_id)
        if normalized["row_id"] == row_id:
            new_avg_cost = _to_float(avg_cost)
            item["price"] = new_avg_cost
            item["avg_cost"] = new_avg_cost
            item["shares"] = _to_int(shares)
            item["family_id"] = family_id
            item["updated_at"] = _utc_now()
            matched = True
            break
    if not matched:
        raise KeyError(f"Portfolio row not found: {row_id}")
    _save_local_portfolio(items)


def delete_portfolio_item(row_id: str, family_id: str) -> None:
    if get_store_status().using_google_sheets:
        _migrate_local_to_sheet(family_id)
        worksheet = _get_worksheet()
        found = _find_sheet_row(worksheet, row_id=row_id, family_id=family_id)
        if not found:
            raise KeyError(f"Portfolio row not found: {row_id}")
        row_index, normalized = found
        normalized["is_deleted"] = True
        normalized["updated_at"] = _utc_now()
        _update_sheet_row(worksheet, row_index, normalized)
        return

    items = _load_local_portfolio()
    filtered_items = [
        item for item in items if normalize_portfolio_item(item, family_id=family_id)["row_id"] != row_id
    ]
    if len(filtered_items) == len(items):
        raise KeyError(f"Portfolio row not found: {row_id}")
    _save_local_portfolio(filtered_items)

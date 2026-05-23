import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from _app_common import get_portfolio_file

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
    return {
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


def get_default_family_id() -> str:
    secrets = _secrets()
    return str(secrets.get("PORTFOLIO_DEFAULT_FAMILY_ID", "lwh38009")).strip()


def _load_local_portfolio() -> list[dict[str, Any]]:
    if not PORTFOLIO_FILE.exists():
        return []

    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as file:
        raw_items = json.load(file)

    return [normalize_portfolio_item(item) for item in raw_items]


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
        worksheet.update("A1:J1", [WORKSHEET_HEADERS])


def _sheet_records() -> list[dict[str, Any]]:
    worksheet = _get_worksheet()
    return worksheet.get_all_records(expected_headers=WORKSHEET_HEADERS)


def _write_sheet_rows(rows: list[dict[str, Any]]) -> None:
    worksheet = _get_worksheet()
    values = [WORKSHEET_HEADERS]
    for row in rows:
        normalized = normalize_portfolio_item(row)
        values.append(
            [
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
        )
    worksheet.clear()
    worksheet.update(values=values, range_name="A1")


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

    return [
        normalize_portfolio_item(item, family_id=family_id)
        for item in _load_local_portfolio()
        if not normalize_portfolio_item(item, family_id=family_id)["is_deleted"]
    ]


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
        rows = _sheet_records()
        rows.append(item)
        _write_sheet_rows(rows)
        return item

    items = _load_local_portfolio()
    items.append(item)
    _save_local_portfolio(items)
    return item


def update_portfolio_item(row_id: str, family_id: str, avg_cost=None, shares=None, note: str | None = None) -> None:
    if get_store_status().using_google_sheets:
        _migrate_local_to_sheet(family_id)
        rows = _sheet_records()
        updated_rows = []
        matched = False
        for row in rows:
            normalized = normalize_portfolio_item(row)
            if normalized["row_id"] == row_id and normalized["family_id"] == family_id:
                normalized["avg_cost"] = _to_float(avg_cost)
                normalized["price"] = normalized["avg_cost"]
                normalized["shares"] = _to_int(shares)
                if note is not None:
                    normalized["note"] = note
                normalized["updated_at"] = _utc_now()
                matched = True
            updated_rows.append(normalized)
        if not matched:
            raise KeyError(f"Portfolio row not found: {row_id}")
        _write_sheet_rows(updated_rows)
        return

    items = _load_local_portfolio()
    matched = False
    for item in items:
        normalized = normalize_portfolio_item(item, family_id=family_id)
        if normalized["row_id"] == row_id:
            item["price"] = _to_float(avg_cost)
            item["shares"] = _to_int(shares)
            item["updated_at"] = _utc_now()
            matched = True
            break
    if not matched:
        raise KeyError(f"Portfolio row not found: {row_id}")
    _save_local_portfolio(items)


def delete_portfolio_item(row_id: str, family_id: str) -> None:
    if get_store_status().using_google_sheets:
        _migrate_local_to_sheet(family_id)
        rows = _sheet_records()
        updated_rows = []
        matched = False
        for row in rows:
            normalized = normalize_portfolio_item(row)
            if normalized["row_id"] == row_id and normalized["family_id"] == family_id:
                normalized["is_deleted"] = True
                normalized["updated_at"] = _utc_now()
                matched = True
            updated_rows.append(normalized)
        if not matched:
            raise KeyError(f"Portfolio row not found: {row_id}")
        _write_sheet_rows(updated_rows)
        return

    items = _load_local_portfolio()
    filtered_items = [
        item for item in items if normalize_portfolio_item(item, family_id=family_id)["row_id"] != row_id
    ]
    if len(filtered_items) == len(items):
        raise KeyError(f"Portfolio row not found: {row_id}")
    _save_local_portfolio(filtered_items)

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from typing import Any
from uuid import uuid4

import pandas as pd
import requests

from backtest_data_layer.double_dragon_snapshot import SnapshotDiagnostics
from data_layer.app_common import get_runtime_secret
from data_layer.time_utils import utc_now_string


RUNS_TABLE = "backtest_runs"
ROWS_TABLE = "backtest_snapshot_rows"
STRATEGY_NAME = "double_dragon"


@dataclass(frozen=True)
class SupabaseStatus:
    configured: bool
    url: str = ""
    message: str = ""


@dataclass(frozen=True)
class StoredBacktestSnapshot:
    run: dict[str, Any]
    snapshot: pd.DataFrame
    diagnostics: SnapshotDiagnostics


class SupabaseBacktestStoreError(RuntimeError):
    pass


def get_supabase_status() -> SupabaseStatus:
    url, key = _supabase_config()
    if not url:
        return SupabaseStatus(False, message="SUPABASE_URL is not configured.")
    if not key:
        return SupabaseStatus(False, url=url, message="SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY is not configured.")
    return SupabaseStatus(True, url=url, message="Supabase configured.")


def save_backtest_snapshot(
    as_of_date: date | datetime | str,
    df_snapshot: pd.DataFrame,
    diagnostics: SnapshotDiagnostics,
    max_targets: int = 0,
) -> str:
    if df_snapshot.empty:
        raise SupabaseBacktestStoreError("Cannot save an empty backtest snapshot.")

    run_id = _new_run_id(as_of_date)
    diagnostics_payload = asdict(diagnostics)
    run_payload = {
        "run_id": run_id,
        "strategy": STRATEGY_NAME,
        "as_of_date": _date_text(as_of_date),
        "max_targets": int(max_targets or 0),
        "snapshot_rows": int(len(df_snapshot)),
        "dragon_count": _truthy_count(df_snapshot, "is_dragon_rise_pass"),
        "hidden_count": _truthy_count(df_snapshot, "is_dragon_hidden_pass"),
        "combined_count": _combined_count(df_snapshot),
        "diagnostics": _jsonable(diagnostics_payload),
    }
    _request("POST", RUNS_TABLE, json_payload=run_payload, prefer="return=representation")

    rows = []
    for row in df_snapshot.to_dict("records"):
        rows.append(
            {
                "run_id": run_id,
                "as_of_date": _date_text(as_of_date),
                "stock_id": str(row.get("stock_id") or "").strip(),
                "branch_label": str(row.get("branch_label") or "").strip(),
                "payload": _jsonable(row),
            }
        )
    for chunk in _chunks(rows, 500):
        _request("POST", ROWS_TABLE, json_payload=chunk, prefer="return=minimal")
    return run_id


def list_backtest_runs(limit: int = 20) -> list[dict[str, Any]]:
    params = {
        "select": "run_id,strategy,as_of_date,max_targets,snapshot_rows,dragon_count,hidden_count,combined_count,created_at",
        "strategy": f"eq.{STRATEGY_NAME}",
        "order": "created_at.desc",
        "limit": str(max(int(limit), 1)),
    }
    payload = _request("GET", RUNS_TABLE, params=params)
    return payload if isinstance(payload, list) else []


def load_backtest_snapshot(run_id: str) -> StoredBacktestSnapshot:
    clean_run_id = str(run_id).strip()
    if not clean_run_id:
        raise SupabaseBacktestStoreError("Missing Supabase run_id.")

    run_payload = _request(
        "GET",
        RUNS_TABLE,
        params={
            "select": "*",
            "run_id": f"eq.{clean_run_id}",
            "limit": "1",
        },
    )
    if not isinstance(run_payload, list) or not run_payload:
        raise SupabaseBacktestStoreError(f"Backtest run not found: {clean_run_id}")
    run = run_payload[0]

    row_payload = _request(
        "GET",
        ROWS_TABLE,
        params={
            "select": "payload",
            "run_id": f"eq.{clean_run_id}",
            "order": "stock_id.asc",
        },
    )
    if not isinstance(row_payload, list):
        row_payload = []
    snapshot = pd.DataFrame([row.get("payload") or {} for row in row_payload])
    if not snapshot.empty and "close" in snapshot.columns:
        snapshot["close"] = pd.to_numeric(snapshot["close"], errors="coerce")
        snapshot = snapshot.sort_values("close", ascending=False).reset_index(drop=True)

    diagnostics = _diagnostics_from_payload(run.get("diagnostics") or {})
    return StoredBacktestSnapshot(run=run, snapshot=snapshot, diagnostics=diagnostics)


def _supabase_config() -> tuple[str, str]:
    url = get_runtime_secret("SUPABASE_URL", "").rstrip("/")
    key = get_runtime_secret("SUPABASE_SERVICE_ROLE_KEY", "") or get_runtime_secret("SUPABASE_ANON_KEY", "")
    return url, key


def _request(
    method: str,
    table: str,
    params: dict[str, str] | None = None,
    json_payload: Any = None,
    prefer: str = "",
) -> Any:
    url, key = _supabase_config()
    if not url or not key:
        raise SupabaseBacktestStoreError(get_supabase_status().message)

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    endpoint = f"{url}/rest/v1/{table}"
    try:
        response = requests.request(method, endpoint, params=params, json=json_payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise SupabaseBacktestStoreError(f"Supabase request failed: {exc}") from exc

    if response.status_code >= 400:
        raise SupabaseBacktestStoreError(f"Supabase {response.status_code}: {response.text[:500]}")
    if not response.text:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _new_run_id(as_of_date: date | datetime | str) -> str:
    token = utc_now_string("%Y%m%dT%H%M%SZ")
    return f"{STRATEGY_NAME}:{_date_text(as_of_date)}:{token}:{uuid4().hex[:8]}"


def _date_text(value: date | datetime | str) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def _truthy_count(df: pd.DataFrame, column: str) -> int:
    if column not in df.columns:
        return 0
    return int(df[column].fillna(False).astype(bool).sum())


def _combined_count(df: pd.DataFrame) -> int:
    if df.empty or "stock_id" not in df.columns:
        return 0
    if {"is_dragon_rise_pass", "is_dragon_hidden_pass"}.issubset(df.columns):
        selected = df[df["is_dragon_rise_pass"].fillna(False).astype(bool) | df["is_dragon_hidden_pass"].fillna(False).astype(bool)]
        return int(selected["stock_id"].nunique())
    return int(df["stock_id"].nunique())


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _jsonable(value.item())
        except (TypeError, ValueError):
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _diagnostics_from_payload(payload: dict[str, Any]) -> SnapshotDiagnostics:
    allowed = {field.name for field in fields(SnapshotDiagnostics)}
    defaults = {
        "stock_count": 0,
        "price_rows": 0,
        "price_volume_candidates": 0,
        "revenue_month_start": "",
        "revenue_rows": 0,
        "revenue_candidates": 0,
        "common_passed": 0,
        "common_failed": 0,
        "processed": 0,
        "price_failed": (),
        "eps_failed": (),
        "rate_limit_error": "",
    }
    data = {key: payload.get(key, defaults[key]) for key in defaults if key in allowed}
    data["price_failed"] = tuple(data.get("price_failed") or ())
    data["eps_failed"] = tuple(data.get("eps_failed") or ())
    return SnapshotDiagnostics(**data)


def _chunks(rows: list[dict[str, Any]], size: int):
    for index in range(0, len(rows), size):
        yield rows[index : index + size]

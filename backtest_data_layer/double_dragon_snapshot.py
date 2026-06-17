from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

import pandas as pd

from backtest_common.double_dragon_rules import (
    DEFAULT_THRESHOLDS,
    DoubleDragonThresholds,
    apply_double_dragon_flags,
    build_revenue_metrics_skip_february,
    calc_price_metrics,
    calc_ttm_eps,
    eps_window_start,
    latest_complete_revenue_ym,
    price_window_start,
)
from backtest_data_layer.finmind_sources import (
    fetch_financial_statement_frame,
    fetch_price_history_frame,
)
from backtest_data_layer.historical_prices import fetch_historical_price_snapshot
from data_layer.mops_revenue import fetch_mops_recent_revenue_frame


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class SnapshotDiagnostics:
    stock_count: int
    price_rows: int
    price_volume_candidates: int
    revenue_month_start: str
    revenue_rows: int
    revenue_candidates: int
    processed: int
    price_failed: tuple[str, ...]
    eps_failed: tuple[str, ...]
    rate_limit_error: str = ""


def _date_text(value: date | datetime | str) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def load_revenue_candidates(
    as_of_date: date | datetime | str,
    thresholds: DoubleDragonThresholds = DEFAULT_THRESHOLDS,
) -> tuple[pd.DataFrame, str, int]:
    latest_ym = latest_complete_revenue_ym(as_of_date)
    df_revenue = fetch_mops_recent_revenue_frame(latest_ym, months=4)
    df_metrics = build_revenue_metrics_skip_february(df_revenue, months=2)
    if df_metrics.empty:
        return df_metrics, latest_ym, len(df_revenue)
    df_candidates = df_metrics[
        pd.to_numeric(df_metrics["avg_rev_yoy"], errors="coerce") >= thresholds.avg_rev_yoy_min
    ].copy()
    return df_candidates.reset_index(drop=True), latest_ym, len(df_revenue)


def load_candidate_universe(
    as_of_date: date | datetime | str,
    token: str = "",
    thresholds: DoubleDragonThresholds = DEFAULT_THRESHOLDS,
) -> tuple[pd.DataFrame, SnapshotDiagnostics]:
    _ = token
    df_price = fetch_historical_price_snapshot(as_of_date)
    df_price_candidates = df_price[
        (pd.to_numeric(df_price["close"], errors="coerce") > thresholds.price_min)
        & (pd.to_numeric(df_price["vol_lot"], errors="coerce") > thresholds.vol_lot_min)
    ].copy()

    df_revenue_candidates, latest_ym, revenue_rows = load_revenue_candidates(as_of_date, thresholds)

    if df_price_candidates.empty or df_revenue_candidates.empty:
        diagnostics = SnapshotDiagnostics(
            stock_count=len(df_price),
            price_rows=len(df_price),
            price_volume_candidates=len(df_price_candidates),
            revenue_month_start=latest_ym,
            revenue_rows=revenue_rows,
            revenue_candidates=0,
            processed=0,
            price_failed=(),
            eps_failed=(),
        )
        return pd.DataFrame(), diagnostics

    df_universe = df_price_candidates.merge(df_revenue_candidates, on="stock_id", how="inner")

    diagnostics = SnapshotDiagnostics(
        stock_count=len(df_price),
        price_rows=len(df_price),
        price_volume_candidates=len(df_price_candidates),
        revenue_month_start=latest_ym,
        revenue_rows=revenue_rows,
        revenue_candidates=len(df_universe),
        processed=0,
        price_failed=(),
        eps_failed=(),
    )
    return df_universe.reset_index(drop=True), diagnostics


def _build_stock_snapshot(row: dict, as_of_date: date | datetime | str, token: str) -> tuple[str, dict | str]:
    stock_id = str(row["stock_id"])
    price_start = price_window_start(as_of_date)
    eps_start = eps_window_start(as_of_date)

    history = fetch_price_history_frame(
        stock_id,
        price_start,
        as_of_date,
        token=token,
        sleep_seconds=1.2,
    )
    price_metrics = calc_price_metrics(
        stock_id,
        str(row.get("stock_name") or stock_id),
        str(row.get("market") or ""),
        history,
        as_of_date,
    )
    if price_metrics is None:
        return "price_failed", stock_id
    price_metrics["price_date"] = str(row.get("price_date") or price_metrics.get("price_date") or "")
    price_metrics["close"] = row.get("close", price_metrics.get("close"))
    price_metrics["vol_lot"] = row.get("vol_lot", price_metrics.get("vol_lot"))

    financial = fetch_financial_statement_frame(
        stock_id,
        eps_start,
        as_of_date,
        token=token,
        sleep_seconds=2.0,
    )
    eps_metrics = calc_ttm_eps(financial, as_of_date)
    if eps_metrics is None:
        return "eps_failed", stock_id

    result = {
        "as_of_date": _date_text(as_of_date),
        **price_metrics,
        "rev_ym": row.get("rev_ym"),
        "rev_yoy": row.get("rev_yoy"),
        "rev_cur": row.get("rev_cur"),
        "rev_ly": row.get("rev_ly"),
        "avg_rev_yoy": row.get("avg_rev_yoy"),
        "rev_months": row.get("rev_months"),
        "latest_rev_yoy": row.get("latest_rev_yoy"),
        "prev_rev_yoy": row.get("prev_rev_yoy"),
        **eps_metrics,
    }
    ttm_eps = pd.to_numeric(result.get("ttm_eps"), errors="coerce")
    close = pd.to_numeric(result.get("close"), errors="coerce")
    result["pe_ratio"] = float(close / ttm_eps) if pd.notna(close) and pd.notna(ttm_eps) and ttm_eps > 0 else pd.NA
    return "ok", result


def build_double_dragon_snapshot(
    as_of_date: date | datetime | str,
    token: str = "",
    max_workers: int = 3,
    max_targets: int = 0,
    progress_callback: ProgressCallback | None = None,
    thresholds: DoubleDragonThresholds = DEFAULT_THRESHOLDS,
) -> tuple[pd.DataFrame, SnapshotDiagnostics]:
    df_universe, base_diagnostics = load_candidate_universe(as_of_date, token=token, thresholds=thresholds)
    if df_universe.empty:
        return pd.DataFrame(), base_diagnostics

    df_targets = df_universe.sort_values(["avg_rev_yoy", "stock_id"], ascending=[False, True]).reset_index(drop=True)
    if max_targets and max_targets > 0:
        df_targets = df_targets.head(int(max_targets)).copy()

    rows: list[dict] = []
    price_failed: list[str] = []
    eps_failed: list[str] = []
    rate_limit_error = ""
    done_count = 0
    target_records = df_targets.to_dict("records")
    target_iter = iter(target_records)
    pending = {}
    worker_count = max(1, min(int(max_workers), 3, len(target_records)))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for _ in range(worker_count):
            try:
                row = next(target_iter)
            except StopIteration:
                break
            pending[executor.submit(_build_stock_snapshot, row, as_of_date, token)] = str(row["stock_id"])

        while pending:
            done, _not_done = wait(list(pending.keys()), return_when=FIRST_COMPLETED)
            for future in done:
                stock_id = pending.pop(future, "")
                done_count += 1
                try:
                    status, payload = future.result()
                except RuntimeError as exc:
                    error_text = str(exc)
                    if "FINMIND_LIMIT" in error_text:
                        rate_limit_error = error_text
                    else:
                        price_failed.append(stock_id)
                    status, payload = "failed", stock_id
                except Exception:
                    status, payload = "failed", stock_id

                if status == "ok" and isinstance(payload, dict):
                    rows.append(payload)
                elif status == "price_failed":
                    price_failed.append(str(payload))
                elif status == "eps_failed":
                    eps_failed.append(str(payload))

                if progress_callback:
                    progress_callback(done_count, len(target_records), stock_id)

                if rate_limit_error:
                    break

                try:
                    row = next(target_iter)
                except StopIteration:
                    continue
                pending[executor.submit(_build_stock_snapshot, row, as_of_date, token)] = str(row["stock_id"])

            if rate_limit_error:
                for future in pending:
                    future.cancel()
                break

    df_snapshot = pd.DataFrame(rows)
    if not df_snapshot.empty:
        df_snapshot = apply_double_dragon_flags(df_snapshot, thresholds)
        df_snapshot = df_snapshot.sort_values("close", ascending=False).reset_index(drop=True)

    diagnostics = SnapshotDiagnostics(
        stock_count=base_diagnostics.stock_count,
        price_rows=base_diagnostics.price_rows,
        price_volume_candidates=base_diagnostics.price_volume_candidates,
        revenue_month_start=base_diagnostics.revenue_month_start,
        revenue_rows=base_diagnostics.revenue_rows,
        revenue_candidates=len(df_targets),
        processed=done_count,
        price_failed=tuple(price_failed[:30]),
        eps_failed=tuple(eps_failed[:30]),
        rate_limit_error=rate_limit_error,
    )
    return df_snapshot, diagnostics

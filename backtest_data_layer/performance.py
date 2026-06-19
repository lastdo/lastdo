from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

import pandas as pd

from backtest_data_layer.finmind_sources import fetch_price_history_frame


ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class PerformanceDiagnostics:
    requested_stocks: int
    priced_stocks: int
    failed_stocks: tuple[str, ...]
    benchmark_id: str
    benchmark_return_pct: float | None
    rate_limit_error: str = ""


def _date_text(value: date | datetime | str) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def _numeric(value) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    return float(number) if pd.notna(number) else None


def _prepare_targets(df_snapshot: pd.DataFrame, max_stocks: int = 0) -> pd.DataFrame:
    columns = ["stock_id", "stock_name", "branch_label", "close", "price_date"]
    if df_snapshot.empty:
        return pd.DataFrame(columns=columns)

    df = df_snapshot.copy()
    if "stock_id" not in df.columns or "close" not in df.columns:
        return pd.DataFrame(columns=columns)
    if "branch_label" not in df.columns:
        df["branch_label"] = ""
    if "stock_name" not in df.columns:
        df["stock_name"] = df["stock_id"]
    if "price_date" not in df.columns:
        df["price_date"] = ""

    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df["start_price"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["stock_id", "start_price"])
    df = df[df["start_price"] > 0].drop_duplicates("stock_id").reset_index(drop=True)
    if max_stocks and max_stocks > 0:
        df = df.head(int(max_stocks)).copy()
    return df[["stock_id", "stock_name", "branch_label", "start_price", "price_date"]]


def _history_after_start(history: pd.DataFrame, as_of_date: date | datetime | str) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    df = history.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    start = pd.Timestamp(pd.to_datetime(as_of_date).date())
    df = df[(df["date"] >= start) & df["close"].notna()].sort_values("date")
    return df.reset_index(drop=True)


def _build_benchmark_curve(
    as_of_date: date | datetime | str,
    end_date: date | datetime | str,
    token: str,
    benchmark_id: str,
) -> tuple[pd.DataFrame, float | None]:
    history = fetch_price_history_frame(
        benchmark_id,
        as_of_date,
        end_date,
        token=token,
        sleep_seconds=1.2,
    )
    df = _history_after_start(history, as_of_date)
    if len(df) < 2:
        return pd.DataFrame(columns=["date", "benchmark_return_pct"]), None

    start_close = _numeric(df.iloc[0].get("close"))
    if not start_close:
        return pd.DataFrame(columns=["date", "benchmark_return_pct"]), None

    curve = pd.DataFrame(
        {
            "date": df["date"],
            "benchmark_return_pct": (df["close"] / start_close - 1) * 100,
        }
    )
    final_return = _numeric(curve.iloc[-1].get("benchmark_return_pct"))
    return curve, final_return


def build_return_analysis(
    df_snapshot: pd.DataFrame,
    as_of_date: date | datetime | str,
    end_date: date | datetime | str,
    token: str = "",
    benchmark_id: str = "TAIEX",
    max_stocks: int = 0,
    progress_callback: ProgressCallback | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict, PerformanceDiagnostics]:
    targets = _prepare_targets(df_snapshot, max_stocks=max_stocks)
    if targets.empty:
        diagnostics = PerformanceDiagnostics(
            requested_stocks=0,
            priced_stocks=0,
            failed_stocks=(),
            benchmark_id=benchmark_id,
            benchmark_return_pct=None,
        )
        return pd.DataFrame(), pd.DataFrame(), {}, diagnostics

    benchmark_curve = pd.DataFrame(columns=["date", "benchmark_return_pct"])
    benchmark_return_pct: float | None = None
    rate_limit_error = ""
    try:
        benchmark_curve, benchmark_return_pct = _build_benchmark_curve(
            as_of_date,
            end_date,
            token=token,
            benchmark_id=benchmark_id,
        )
    except RuntimeError as exc:
        if "FINMIND_LIMIT" in str(exc):
            rate_limit_error = str(exc)
        else:
            raise

    rows: list[dict] = []
    curve_parts: list[pd.DataFrame] = []
    failed: list[str] = []

    if not rate_limit_error:
        records = targets.to_dict("records")
        for index, row in enumerate(records, start=1):
            stock_id = str(row["stock_id"])
            try:
                history = fetch_price_history_frame(
                    stock_id,
                    as_of_date,
                    end_date,
                    token=token,
                    sleep_seconds=1.2,
                )
            except RuntimeError as exc:
                if "FINMIND_LIMIT" in str(exc):
                    rate_limit_error = str(exc)
                    break
                failed.append(stock_id)
                continue
            except Exception:
                failed.append(stock_id)
                continue

            history = _history_after_start(history, as_of_date)
            start_price = _numeric(row.get("start_price"))
            end_price = _numeric(history.iloc[-1].get("close")) if not history.empty else None
            if not start_price or not end_price:
                failed.append(stock_id)
                continue

            stock_return_pct = (end_price / start_price - 1) * 100
            rows.append(
                {
                    "stock_id": stock_id,
                    "stock_name": row.get("stock_name") or stock_id,
                    "branch_label": row.get("branch_label") or "",
                    "start_date": _date_text(row.get("price_date") or as_of_date),
                    "end_date": _date_text(history.iloc[-1].get("date")),
                    "start_price": start_price,
                    "end_price": end_price,
                    "stock_return_pct": stock_return_pct,
                    "benchmark_return_pct": benchmark_return_pct,
                    "excess_return_pct": (
                        stock_return_pct - benchmark_return_pct
                        if benchmark_return_pct is not None
                        else pd.NA
                    ),
                }
            )

            curve = pd.DataFrame(
                {
                    "date": history["date"],
                    stock_id: (history["close"] / start_price - 1) * 100,
                }
            )
            curve_parts.append(curve)

            if progress_callback:
                progress_callback(index, len(records), stock_id)

    return_df = pd.DataFrame(rows)
    curve_df = _combine_curves(curve_parts, benchmark_curve)
    kpis = _build_kpis(return_df, benchmark_return_pct, len(targets))
    diagnostics = PerformanceDiagnostics(
        requested_stocks=len(targets),
        priced_stocks=len(return_df),
        failed_stocks=tuple(failed[:30]),
        benchmark_id=benchmark_id,
        benchmark_return_pct=benchmark_return_pct,
        rate_limit_error=rate_limit_error,
    )
    return return_df, curve_df, kpis, diagnostics


def _combine_curves(curve_parts: list[pd.DataFrame], benchmark_curve: pd.DataFrame) -> pd.DataFrame:
    if not curve_parts:
        portfolio = pd.DataFrame(columns=["date", "portfolio_return_pct", "priced_count"])
    else:
        merged = curve_parts[0]
        for curve in curve_parts[1:]:
            merged = merged.merge(curve, on="date", how="outer")
        merged = merged.sort_values("date").reset_index(drop=True)
        value_columns = [column for column in merged.columns if column != "date"]
        portfolio = pd.DataFrame(
            {
                "date": merged["date"],
                "portfolio_return_pct": merged[value_columns].mean(axis=1, skipna=True),
                "priced_count": merged[value_columns].notna().sum(axis=1),
            }
        )

    if benchmark_curve.empty:
        portfolio["benchmark_return_pct"] = pd.NA
    else:
        portfolio = portfolio.merge(benchmark_curve, on="date", how="outer").sort_values("date")
    portfolio["excess_return_pct"] = (
        pd.to_numeric(portfolio.get("portfolio_return_pct"), errors="coerce")
        - pd.to_numeric(portfolio.get("benchmark_return_pct"), errors="coerce")
    )
    return portfolio.reset_index(drop=True)


def _build_kpis(return_df: pd.DataFrame, benchmark_return_pct: float | None, requested_stocks: int) -> dict:
    if return_df.empty:
        return {
            "requested_stocks": requested_stocks,
            "priced_stocks": 0,
            "portfolio_return_pct": None,
            "benchmark_return_pct": benchmark_return_pct,
            "excess_return_pct": None,
            "win_rate_pct": None,
            "median_return_pct": None,
            "best_stock": "",
            "worst_stock": "",
        }

    returns = pd.to_numeric(return_df["stock_return_pct"], errors="coerce").dropna()
    portfolio_return = float(returns.mean()) if not returns.empty else None
    excess_return = (
        portfolio_return - benchmark_return_pct
        if portfolio_return is not None and benchmark_return_pct is not None
        else None
    )
    best = return_df.sort_values("stock_return_pct", ascending=False).iloc[0]
    worst = return_df.sort_values("stock_return_pct", ascending=True).iloc[0]
    return {
        "requested_stocks": requested_stocks,
        "priced_stocks": len(return_df),
        "portfolio_return_pct": portfolio_return,
        "benchmark_return_pct": benchmark_return_pct,
        "excess_return_pct": excess_return,
        "win_rate_pct": float((returns > 0).mean() * 100) if not returns.empty else None,
        "median_return_pct": float(returns.median()) if not returns.empty else None,
        "best_stock": f"{best['stock_id']} {best.get('stock_name', '')}".strip(),
        "worst_stock": f"{worst['stock_id']} {worst.get('stock_name', '')}".strip(),
    }

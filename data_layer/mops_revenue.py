from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd
from twmops import RevenueFetcher


MOPS_MARKETS = ("sii", "otc")
MOPS_COMPANY_TYPES = (0, 1)


def latest_revenue_ym(today: date | datetime | None = None) -> str:
    """Return the most recent complete revenue month in ROC yyyMM format."""
    current = today.date() if isinstance(today, datetime) else today
    current = current or date.today()
    previous_month = current.replace(day=1) - timedelta(days=1)
    return f"{previous_month.year - 1911}{previous_month.month:02d}"


def previous_revenue_ym(ym: str) -> str:
    clean = str(ym).strip().replace("/", "")
    if len(clean) != 5 or not clean.isdigit():
        return ""
    roc_year = int(clean[:3])
    month = int(clean[3:])
    month -= 1
    if month == 0:
        roc_year -= 1
        month = 12
    return f"{roc_year}{month:02d}"


def _normalize_revenue_frame(raw: object, market: str, company_type: int, ym: str) -> pd.DataFrame:
    if raw is None:
        return pd.DataFrame()

    if isinstance(raw, list) and raw and hasattr(raw[0], "model_dump"):
        df = pd.DataFrame([row.model_dump() for row in raw])
    elif isinstance(raw, list) and raw and hasattr(raw[0], "dict"):
        df = pd.DataFrame([row.dict() for row in raw])
    elif isinstance(raw, list) and raw and isinstance(raw[0], (list, tuple)):
        df = pd.DataFrame([dict(row) for row in raw])
    else:
        df = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
    if df.empty:
        return pd.DataFrame()

    if "company_code" in df.columns and "stock_id" not in df.columns:
        df = df.rename(columns={"company_code": "stock_id"})

    required = {"stock_id", "company_name", "revenue", "revenue_last_year", "yoy_change"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    if {"year", "month"}.issubset(df.columns):
        requested_year = int(ym[:3])
        requested_month = int(ym[3:])
        df = df[
            (pd.to_numeric(df["year"], errors="coerce") == requested_year)
            & (pd.to_numeric(df["month"], errors="coerce") == requested_month)
        ].copy()
        if df.empty:
            return pd.DataFrame()

    normalized = pd.DataFrame(
        {
            "stock_id": df["stock_id"].astype(str).str.strip(),
            "stock_name_mops": df["company_name"].astype(str).str.strip(),
            "rev_ym": ym,
            "rev_yoy": pd.to_numeric(df["yoy_change"], errors="coerce"),
            "rev_cur": pd.to_numeric(df["revenue"], errors="coerce"),
            "rev_ly": pd.to_numeric(df["revenue_last_year"], errors="coerce"),
            "mops_market": market,
            "mops_company_type": company_type,
            "mops_comment": df.get("comment", pd.Series("", index=df.index)).astype(str).str.strip(),
        }
    )
    normalized = normalized.dropna(subset=["stock_id", "rev_yoy"])
    normalized = normalized[normalized["stock_id"].str.fullmatch(r"\d{4}")]
    return normalized


def fetch_mops_month_revenue_frame(
    roc_year: int,
    month: int,
    markets: Iterable[str] = MOPS_MARKETS,
    company_types: Iterable[int] = MOPS_COMPANY_TYPES,
) -> pd.DataFrame:
    fetcher = RevenueFetcher()
    ym = f"{int(roc_year)}{int(month):02d}"
    frames: list[pd.DataFrame] = []

    for market in markets:
        for company_type in company_types:
            raw = fetcher.get_market_revenue(int(roc_year), int(month), str(market), int(company_type))
            frame = _normalize_revenue_frame(raw, str(market), int(company_type), ym)
            if not frame.empty:
                frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["stock_id", "rev_ym", "rev_yoy", "rev_cur", "rev_ly"])

    result = pd.concat(frames, ignore_index=True)
    return result.drop_duplicates(subset=["stock_id", "rev_ym"], keep="first").reset_index(drop=True)


def fetch_mops_recent_revenue_frame(latest_ym: str | None = None, months: int = 1) -> pd.DataFrame:
    ym = latest_ym or latest_revenue_ym()
    month_frames: list[pd.DataFrame] = []

    for _ in range(max(int(months), 1)):
        if not ym:
            break
        frame = fetch_mops_month_revenue_frame(int(ym[:3]), int(ym[3:]))
        if not frame.empty:
            month_frames.append(frame)
        ym = previous_revenue_ym(ym)

    if not month_frames:
        return pd.DataFrame(columns=["stock_id", "rev_ym", "rev_yoy", "rev_cur", "rev_ly"])

    return pd.concat(month_frames, ignore_index=True).reset_index(drop=True)

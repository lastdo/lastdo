from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd


@dataclass(frozen=True)
class DoubleDragonThresholds:
    price_min: float = 60.0
    vol_lot_min: float = 1000.0
    avg_rev_yoy_min: float = 20.0
    ttm_eps_min: float = 5.0
    dragon_pe_max: float = 30.0
    dragon_ma60_max_premium: float = 0.30
    dragon_ma240_max_premium: float = 0.30
    hidden_dragon_pe_max: float = 20.0
    hidden_dragon_low_max_premium: float = 0.20


DEFAULT_THRESHOLDS = DoubleDragonThresholds()


def normalize_as_of_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.to_datetime(value).date()


def previous_roc_month(ym: str) -> str:
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


def latest_complete_revenue_ym(as_of_date: date | datetime | str) -> str:
    current = normalize_as_of_date(as_of_date)
    previous_month = current.replace(day=1) - timedelta(days=1)
    return f"{previous_month.year - 1911}{previous_month.month:02d}"


def price_window_start(as_of_date: date | datetime | str, months: int = 12) -> date:
    current = normalize_as_of_date(as_of_date)
    return current - timedelta(days=int(months * 31) + 45)


def eps_window_start(as_of_date: date | datetime | str) -> date:
    current = normalize_as_of_date(as_of_date)
    return current - timedelta(days=760)


def roc_month_number(ym: str) -> int | None:
    clean = str(ym).strip().replace("/", "")
    if len(clean) < 5 or not clean[-2:].isdigit():
        return None
    month = int(clean[-2:])
    return month if 1 <= month <= 12 else None


def build_revenue_metrics_skip_february(df_rev: pd.DataFrame, months: int = 2) -> pd.DataFrame:
    columns = [
        "stock_id",
        "rev_ym",
        "rev_yoy",
        "rev_cur",
        "rev_ly",
        "avg_rev_yoy",
        "rev_months",
        "latest_rev_yoy",
        "prev_rev_yoy",
    ]
    if df_rev.empty:
        return pd.DataFrame(columns=columns)

    df = df_rev.copy()
    df["stock_id"] = df["stock_id"].astype(str).str.strip()
    df["rev_yoy"] = pd.to_numeric(df["rev_yoy"], errors="coerce")
    df = df.dropna(subset=["stock_id", "rev_ym", "rev_yoy"])
    df = df[df["rev_ym"].map(roc_month_number) != 2].copy()
    if df.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for stock_id, group in df.sort_values("rev_ym", ascending=False).groupby("stock_id"):
        selected = group.head(months).copy()
        if len(selected) < months:
            continue
        latest = selected.iloc[0]
        prev = selected.iloc[1]
        rows.append(
            {
                "stock_id": stock_id,
                "rev_ym": latest["rev_ym"],
                "rev_yoy": latest["rev_yoy"],
                "rev_cur": latest.get("rev_cur", pd.NA),
                "rev_ly": latest.get("rev_ly", pd.NA),
                "avg_rev_yoy": selected["rev_yoy"].mean(),
                "rev_months": "/".join(selected["rev_ym"].astype(str).tolist()),
                "latest_rev_yoy": latest["rev_yoy"],
                "prev_rev_yoy": prev["rev_yoy"],
            }
        )
    return pd.DataFrame(rows, columns=columns)


def calc_price_metrics(
    stock_id: str,
    stock_name: str,
    market: str,
    history_df: pd.DataFrame,
    as_of_date: date | datetime | str,
) -> dict | None:
    if history_df.empty:
        return None

    current = pd.Timestamp(normalize_as_of_date(as_of_date))
    df = history_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ("close", "low", "volume"):
        df[column] = pd.to_numeric(df.get(column), errors="coerce")
    df = df[df["date"] <= current].dropna(subset=["date", "close", "low"]).sort_values("date")
    if len(df) < 60:
        return None

    snapshot = df.iloc[-1]
    low_window_start = current - timedelta(days=int(6 * 31))
    low_df = df[df["date"] >= low_window_start]
    if low_df.empty:
        low_df = df
    low_idx = low_df["low"].idxmin()
    low_row = df.loc[low_idx]
    close = float(snapshot["close"])
    ma60 = float(df["close"].tail(60).mean())
    ma240 = float(df["close"].tail(240).mean()) if len(df) >= 240 else pd.NA
    six_month_low = float(low_row["low"])
    vol_lot = float(snapshot["volume"]) / 1000 if pd.notna(snapshot.get("volume")) else pd.NA

    return {
        "stock_id": str(stock_id),
        "stock_name": str(stock_name),
        "market": str(market),
        "price_date": pd.to_datetime(snapshot["date"]).strftime("%Y-%m-%d"),
        "close": close,
        "vol_lot": vol_lot,
        "ma60": ma60,
        "ma240": ma240,
        "six_month_low": six_month_low,
        "six_month_low_date": pd.to_datetime(low_row["date"]).strftime("%Y-%m-%d"),
        "ma60_premium_pct": (close / ma60 - 1) * 100 if ma60 > 0 else pd.NA,
        "ma240_premium_pct": (close / ma240 - 1) * 100 if pd.notna(ma240) and ma240 > 0 else pd.NA,
        "low_premium_pct": (close / six_month_low - 1) * 100 if six_month_low > 0 else pd.NA,
        "history_days": len(df),
    }


def calc_ttm_eps(financial_df: pd.DataFrame, as_of_date: date | datetime | str) -> dict | None:
    if financial_df.empty:
        return None
    if "date" not in financial_df.columns or "type" not in financial_df.columns or "value" not in financial_df.columns:
        return None

    current = pd.Timestamp(normalize_as_of_date(as_of_date))
    df = financial_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    eps = df[(df["type"] == "EPS") & (df["date"] <= current)].dropna(subset=["date", "value"])
    eps = eps.sort_values("date").tail(4)
    if len(eps) < 4:
        return None
    return {
        "ttm_eps": float(eps["value"].sum()),
        "eps_quarters": "/".join(eps["date"].dt.strftime("%Y-%m-%d").tolist()),
    }


def apply_double_dragon_flags(
    df: pd.DataFrame,
    thresholds: DoubleDragonThresholds = DEFAULT_THRESHOLDS,
) -> pd.DataFrame:
    result = df.copy()
    for column in ("close", "vol_lot", "avg_rev_yoy", "ttm_eps", "pe_ratio", "ma60", "ma240", "six_month_low"):
        result[column] = pd.to_numeric(result.get(column), errors="coerce")

    result["is_common_pass"] = (
        (result["close"] > thresholds.price_min)
        & (result["vol_lot"] > thresholds.vol_lot_min)
        & (result["avg_rev_yoy"] >= thresholds.avg_rev_yoy_min)
        & (result["ttm_eps"] >= thresholds.ttm_eps_min)
    )
    result["is_dragon_rise_pass"] = (
        result["is_common_pass"]
        & (result["close"] > result["ma60"])
        & (result["close"] <= result["ma60"] * (1 + thresholds.dragon_ma60_max_premium))
        & (result["close"] <= result["ma240"] * (1 + thresholds.dragon_ma240_max_premium))
        & (result["pe_ratio"] <= thresholds.dragon_pe_max)
    )
    result["is_dragon_hidden_pass"] = (
        result["is_common_pass"]
        & (result["close"] <= result["six_month_low"] * (1 + thresholds.hidden_dragon_low_max_premium))
        & (result["pe_ratio"] <= thresholds.hidden_dragon_pe_max)
    )
    return result

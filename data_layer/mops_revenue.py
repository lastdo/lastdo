from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO
from typing import Iterable
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import pandas as pd
from twmops import RevenueFetcher

from data_layer.time_utils import taipei_today


MOPS_MARKETS = ("sii", "otc")
MOPS_COMPANY_TYPES = (0, 1)
MOPS_REVENUE_COLUMNS = ["stock_id", "rev_ym", "rev_yoy", "rev_cur", "rev_ly"]
MOPS_REVENUE_HOST = "mopsov.twse.com.tw"
MOPS_REVENUE_BASE = f"https://{MOPS_REVENUE_HOST}"
MOPS_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "DNT": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

MOPS_FIELD_ALIASES = {
    "stock_id": (("\u516c\u53f8", "\u4ee3\u865f"),),
    "company_name": (("\u516c\u53f8\u540d\u7a31",),),
    "revenue": (("\u71df\u696d\u6536\u5165", "\u7576\u6708\u71df\u6536"),),
    "revenue_last_year": (("\u71df\u696d\u6536\u5165", "\u53bb\u5e74\u7576\u6708\u71df\u6536"),),
    "yoy_change": (("\u71df\u696d\u6536\u5165", "\u53bb\u5e74\u540c\u6708", "\u589e\u6e1b"),),
    "comment": (("\u5099\u8a3b",),),
}


def _empty_revenue_frame(errors: list[str] | None = None) -> pd.DataFrame:
    df = pd.DataFrame(columns=MOPS_REVENUE_COLUMNS)
    if errors:
        df.attrs["mops_errors"] = errors[:30]
    return df


def latest_revenue_ym(today: date | datetime | None = None) -> str:
    """Return the most recent complete revenue month in ROC yyyMM format."""
    current = today.date() if isinstance(today, datetime) else today
    current = current or taipei_today()
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


def _clean_mops_column_text(value: object) -> str:
    text = str(value)
    for token in ("Unnamed:", "_level_", "nan", "None"):
        text = text.replace(token, "")
    for whitespace in ("\u3000", "\xa0", "\n", "\r", "\t", " "):
        text = text.replace(whitespace, "")
    return text.strip()


def _flatten_mops_column(column: object) -> str:
    if isinstance(column, tuple):
        return "".join(_clean_mops_column_text(part) for part in column)
    return _clean_mops_column_text(column)


def _find_mops_column(columns: Iterable[object], aliases: tuple[tuple[str, ...], ...]) -> object | None:
    flattened = [(column, _flatten_mops_column(column)) for column in columns]
    for alias in aliases:
        needles = [_clean_mops_column_text(part) for part in alias]
        for column, text in flattened:
            if all(needle in text for needle in needles):
                return column
    return None


def _parse_mops_revenue_tables(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for df in dfs:
        if df.empty or df.shape[1] < 5:
            continue

        selected: dict[str, object] = {}
        for field, aliases in MOPS_FIELD_ALIASES.items():
            column = _find_mops_column(df.columns, aliases)
            if column is not None:
                selected[field] = column

        required = {"stock_id", "company_name", "revenue", "revenue_last_year", "yoy_change"}
        if not required.issubset(selected):
            continue

        parsed = pd.DataFrame({field: df[column] for field, column in selected.items()})
        parsed = parsed[parsed["stock_id"].astype(str).str.strip().str.fullmatch(r"\d{4}", na=False)]
        if not parsed.empty:
            frames.append(parsed)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


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


def _candidate_revenue_urls(url: str) -> list[str]:
    parsed = urlparse(str(url))
    urls = [str(url)]
    if parsed.netloc and parsed.netloc != MOPS_REVENUE_HOST:
        urls.append(urlunparse(parsed._replace(scheme="https", netloc=MOPS_REVENUE_HOST)))
    return list(dict.fromkeys(urls))


def _mops_request_headers(fetcher: RevenueFetcher, url: str, referer: str | None = None) -> dict[str, str]:
    headers = dict(fetcher.client._get_headers(referer or MOPS_REVENUE_BASE))
    headers.update(MOPS_BROWSER_HEADERS)
    headers["Referer"] = referer or f"{MOPS_REVENUE_BASE}/"
    return headers


def _mops_warmup_urls(target_url: str) -> list[str]:
    parsed = urlparse(str(target_url))
    urls = [f"{MOPS_REVENUE_BASE}/"]
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[:2] == ["nas", "t21"]:
        urls.append(f"{MOPS_REVENUE_BASE}/nas/t21/{path_parts[2]}/")
    return list(dict.fromkeys(urls))


def _warm_mops_browser_session(session: httpx.Client, fetcher: RevenueFetcher, target_url: str) -> None:
    referer = None
    for warmup_url in _mops_warmup_urls(target_url):
        try:
            session.get(
                warmup_url,
                headers=_mops_request_headers(fetcher, warmup_url, referer=referer),
            )
        except httpx.HTTPError:
            pass
        referer = warmup_url


def _fetch_market_revenue_with_redirects(
    fetcher: RevenueFetcher,
    roc_year: int,
    month: int,
    market: str,
    company_type: int,
) -> object:
    timeout = getattr(fetcher.client, "timeout", 20)
    errors: list[str] = []

    for url in _candidate_revenue_urls(fetcher._get_revenue_url(roc_year, month, market, company_type)):
        headers = _mops_request_headers(fetcher, url)
        for verify_ssl in (True, False):
            try:
                with httpx.Client(
                    timeout=timeout,
                    follow_redirects=True,
                    verify=verify_ssl,
                    max_redirects=8,
                ) as session:
                    _warm_mops_browser_session(session, fetcher, url)
                    response = session.get(url, headers=headers)
                    if response.is_redirect and response.headers.get("location"):
                        redirect_url = urljoin(str(response.url), response.headers["location"])
                        response = session.get(
                            redirect_url,
                            headers=_mops_request_headers(fetcher, redirect_url, referer=url),
                        )
                if response.status_code == 404:
                    errors.append(f"{url} returned 404")
                    break
                response.raise_for_status()
                response.encoding = "big5"
                dfs = pd.read_html(StringIO(response.text))
                return _parse_mops_revenue_tables(dfs)
            except httpx.ConnectError:
                if not verify_ssl:
                    errors.append(f"{url} connect failed")
            except httpx.HTTPStatusError as exc:
                errors.append(f"{url} HTTP {exc.response.status_code}")
                break

    if errors:
        raise RuntimeError("; ".join(errors))
    return []


def fetch_mops_month_revenue_frame(
    roc_year: int,
    month: int,
    markets: Iterable[str] = MOPS_MARKETS,
    company_types: Iterable[int] = MOPS_COMPANY_TYPES,
) -> pd.DataFrame:
    fetcher = RevenueFetcher()
    ym = f"{int(roc_year)}{int(month):02d}"
    frames: list[pd.DataFrame] = []
    errors: list[str] = []

    for market in markets:
        for company_type in company_types:
            try:
                raw = _fetch_market_revenue_with_redirects(
                    fetcher,
                    int(roc_year),
                    int(month),
                    str(market),
                    int(company_type),
                )
            except Exception as primary_exc:
                try:
                    raw = fetcher.get_market_revenue(int(roc_year), int(month), str(market), int(company_type))
                except Exception as fallback_exc:
                    errors.append(
                        f"{ym} {market}/{company_type}: "
                        f"direct {type(primary_exc).__name__}: {primary_exc}; "
                        f"twmops {type(fallback_exc).__name__}: {fallback_exc}"
                    )
                    continue
            frame = _normalize_revenue_frame(raw, str(market), int(company_type), ym)
            if not frame.empty:
                frames.append(frame)
            else:
                errors.append(f"{ym} {market}/{company_type}: empty or missing expected columns")

    if not frames:
        return _empty_revenue_frame(errors)

    result = pd.concat(frames, ignore_index=True)
    result = result.drop_duplicates(subset=["stock_id", "rev_ym"], keep="first").reset_index(drop=True)
    if errors:
        result.attrs["mops_errors"] = errors[:30]
    return result


def fetch_mops_recent_revenue_frame(latest_ym: str | None = None, months: int = 1) -> pd.DataFrame:
    ym = latest_ym or latest_revenue_ym()
    month_frames: list[pd.DataFrame] = []
    errors: list[str] = []
    target_months = max(int(months), 1)
    max_scan_months = target_months + 6

    for _ in range(max_scan_months):
        if not ym:
            break
        frame = fetch_mops_month_revenue_frame(int(ym[:3]), int(ym[3:]))
        errors.extend(str(error) for error in frame.attrs.get("mops_errors", []))
        if not frame.empty:
            month_frames.append(frame)
            if len(month_frames) >= target_months:
                break
        ym = previous_revenue_ym(ym)

    if not month_frames:
        return _empty_revenue_frame(errors)

    result = pd.concat(month_frames, ignore_index=True).reset_index(drop=True)
    if errors:
        result.attrs["mops_errors"] = errors[:30]
    return result

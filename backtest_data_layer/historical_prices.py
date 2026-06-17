from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import requests

from data_layer.market_api import DEFAULT_HEADERS, URL_TWSE_MI_INDEX, parse_twse_mi_index_price_rows
from data_layer.market_data import clean_numeric


URL_TPEX_DAILY_CLOSE = (
    "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/"
    "stk_quote_result.php?l=zh-tw&o=json&d={date_roc}&s=0,all"
)


def _normalize_date(value: date | datetime | str) -> date:
    return pd.to_datetime(value).date()


def _date_candidates(as_of_date: date | datetime | str, days: int = 10) -> list[date]:
    current = _normalize_date(as_of_date)
    return [current - timedelta(days=offset) for offset in range(days)]


def _fetch_json(url: str):
    last_exc = None
    for _attempt in range(3):
        try:
            response = requests.get(url, timeout=30, headers=DEFAULT_HEADERS)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exc = exc
    raise last_exc


def _to_roc_date(value: date) -> str:
    return f"{value.year - 1911}/{value.month:02d}/{value.day:02d}"


def fetch_twse_historical_price_rows(as_of_date: date | datetime | str) -> list[dict]:
    for candidate in _date_candidates(as_of_date):
        payload = _fetch_json(URL_TWSE_MI_INDEX.format(date=candidate.strftime("%Y%m%d")))
        rows = parse_twse_mi_index_price_rows(payload)
        if rows:
            return rows
    return []


def _parse_tpex_field_rows(payload: dict, price_date: str) -> list[dict]:
    fields = payload.get("fields") or payload.get("iTotalRecords") or []
    data_rows = payload.get("data") or payload.get("aaData") or []
    if not isinstance(fields, list) or not isinstance(data_rows, list):
        return []

    def find_index(candidates: tuple[str, ...]) -> int | None:
        for candidate in candidates:
            for index, field in enumerate(fields):
                if candidate in str(field):
                    return index
        return None

    idx_code = find_index(("代號", "Code"))
    idx_name = find_index(("名稱", "Name"))
    idx_close = find_index(("收盤", "Close"))
    idx_volume = find_index(("成交股數", "成交仟股", "成交張數", "Volume", "TradingShares"))
    if idx_code is None or idx_name is None or idx_close is None:
        return []

    rows = []
    for values in data_rows:
        if not isinstance(values, list) or len(values) <= max(idx_code, idx_name, idx_close):
            continue
        rows.append(
            {
                "stock_id": str(values[idx_code]).strip(),
                "stock_name": str(values[idx_name]).strip(),
                "market": "TPEX",
                "close": values[idx_close],
                "vol_shares": values[idx_volume] if idx_volume is not None and len(values) > idx_volume else "0",
                "price_date": price_date,
            }
        )
    return rows


def parse_tpex_historical_price_rows(payload, price_date: str = "") -> list[dict]:
    if isinstance(payload, list):
        rows = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "stock_id": str(item.get("SecuritiesCompanyCode") or item.get("Code") or "").strip(),
                    "stock_name": str(item.get("CompanyName") or item.get("Name") or "").strip(),
                    "market": "TPEX",
                    "close": item.get("Close"),
                    "vol_shares": item.get("TradingShares") or item.get("Volume") or "0",
                    "price_date": price_date,
                }
            )
        return [row for row in rows if row["stock_id"]]
    if isinstance(payload, dict):
        return _parse_tpex_field_rows(payload, price_date)
    return []


def fetch_tpex_historical_price_rows(as_of_date: date | datetime | str) -> list[dict]:
    for candidate in _date_candidates(as_of_date):
        payload = _fetch_json(URL_TPEX_DAILY_CLOSE.format(date_roc=_to_roc_date(candidate)))
        rows = parse_tpex_historical_price_rows(payload, candidate.strftime("%Y-%m-%d"))
        if rows:
            return rows
    return []


def build_historical_price_snapshot(
    raw_twse_rows: list[dict],
    raw_tpex_rows: list[dict],
) -> pd.DataFrame:
    frames = []
    if raw_twse_rows:
        df_twse = pd.DataFrame(raw_twse_rows)
        frames.append(
            pd.DataFrame(
                {
                    "stock_id": df_twse["Code"].astype(str).str.strip(),
                    "stock_name": df_twse["Name"].astype(str).str.strip(),
                    "market": "TWSE",
                    "price_date": df_twse.get("Date", "").astype(str).str.strip(),
                    "close": clean_numeric(df_twse["ClosingPrice"]),
                    "vol_lot": clean_numeric(df_twse["TradeVolume"]) / 1000,
                }
            )
        )
    if raw_tpex_rows:
        df_tpex = pd.DataFrame(raw_tpex_rows)
        frames.append(
            pd.DataFrame(
                {
                    "stock_id": df_tpex["stock_id"].astype(str).str.strip(),
                    "stock_name": df_tpex["stock_name"].astype(str).str.strip(),
                    "market": "TPEX",
                    "price_date": df_tpex.get("price_date", "").astype(str).str.strip(),
                    "close": clean_numeric(df_tpex["close"]),
                    "vol_lot": _normalize_tpex_volume_lot(df_tpex["vol_shares"]),
                }
            )
        )

    if not frames:
        return pd.DataFrame(columns=["stock_id", "stock_name", "market", "price_date", "close", "vol_lot"])

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["stock_id", "close", "vol_lot"])
    df = df[df["stock_id"].str.fullmatch(r"\d{4}")].copy()
    return df.drop_duplicates("stock_id").reset_index(drop=True)


def _normalize_tpex_volume_lot(series: pd.Series) -> pd.Series:
    values = clean_numeric(series)
    # Historical TPEX JSON often uses thousand shares; latest OpenAPI uses shares.
    if values.dropna().median() < 100000:
        return values
    return values / 1000


def fetch_historical_price_snapshot(as_of_date: date | datetime | str) -> pd.DataFrame:
    raw_twse = fetch_twse_historical_price_rows(as_of_date)
    raw_tpex = fetch_tpex_historical_price_rows(as_of_date)
    return build_historical_price_snapshot(raw_twse, raw_tpex)

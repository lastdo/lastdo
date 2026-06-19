from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd
import requests

from data_layer.app_common import FINMIND_URL
from data_layer.finmind_api import get_result_message, get_retry_after, get_status_code, is_rate_limited


def _date_text(value: date | datetime | str) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def _result_payload(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def fetch_finmind_dataset_frame(
    dataset: str,
    data_id: str | None = None,
    start_date: date | datetime | str | None = None,
    end_date: date | datetime | str | None = None,
    token: str = "",
    timeout: int = 30,
    sleep_seconds: float = 1.2,
    raise_on_rate_limit: bool = True,
) -> tuple[pd.DataFrame, int | None, str, object]:
    params: dict[str, str] = {"dataset": dataset}
    if data_id:
        params["data_id"] = str(data_id)
    if start_date is not None:
        params["start_date"] = _date_text(start_date)
    if end_date is not None:
        params["end_date"] = _date_text(end_date)
    if token:
        params["token"] = token

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    response = requests.get(FINMIND_URL, params=params, timeout=timeout)
    result = _result_payload(response)
    status_code = get_status_code(result) or response.status_code
    msg = get_result_message(result)
    retry_after = get_retry_after(result)

    if response.status_code in (402, 403, 429) or is_rate_limited(result):
        if raise_on_rate_limit:
            raise RuntimeError(f"FINMIND_LIMIT:{status_code}:{retry_after}:{msg}")
        return pd.DataFrame(), status_code, msg, retry_after
    if response.status_code >= 400:
        response.raise_for_status()
    if status_code != 200 or not result.get("data"):
        return pd.DataFrame(), status_code, msg, retry_after
    return pd.DataFrame(result["data"]), status_code, msg, retry_after


def fetch_stock_info_frame(token: str = "") -> pd.DataFrame:
    df, _status, _msg, _retry_after = fetch_finmind_dataset_frame(
        "TaiwanStockInfo",
        token=token,
        sleep_seconds=0,
    )
    if df.empty:
        return pd.DataFrame(columns=["stock_id", "stock_name", "market"])

    result = df.copy()
    result["stock_id"] = result["stock_id"].astype(str).str.strip()
    result = result[result["stock_id"].str.fullmatch(r"\d{4}")].copy()
    if "stock_name" not in result.columns:
        result["stock_name"] = result["stock_id"]
    if "market" not in result.columns:
        result["market"] = result.get("type", "")
    return result[["stock_id", "stock_name", "market"]].drop_duplicates("stock_id")


def fetch_price_history_frame(
    stock_id: str,
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    token: str = "",
    sleep_seconds: float = 1.2,
) -> pd.DataFrame:
    df, _status, _msg, _retry_after = fetch_finmind_dataset_frame(
        "TaiwanStockPrice",
        data_id=stock_id,
        start_date=start_date,
        end_date=end_date,
        token=token,
        sleep_seconds=sleep_seconds,
    )
    if df.empty:
        return pd.DataFrame()
    result = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"}).copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_financial_statement_frame(
    stock_id: str,
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    token: str = "",
    sleep_seconds: float = 2.0,
) -> pd.DataFrame:
    df, _status, _msg, _retry_after = fetch_finmind_dataset_frame(
        "TaiwanStockFinancialStatements",
        data_id=stock_id,
        start_date=start_date,
        end_date=end_date,
        token=token,
        sleep_seconds=sleep_seconds,
    )
    if df.empty:
        return pd.DataFrame()
    result = df.copy()
    result["date"] = pd.to_datetime(result.get("date"), errors="coerce")
    result["value"] = pd.to_numeric(result.get("value"), errors="coerce")
    return result.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

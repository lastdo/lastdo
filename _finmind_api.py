import requests
import pandas as pd

from _app_common import FINMIND_URL


def fetch_finmind_result(params: dict, timeout: int = 20) -> dict:
    resp = requests.get(FINMIND_URL, params=params, timeout=timeout)
    return resp.json()


def get_status_code(result: dict):
    status = result.get("status")
    return int(status) if str(status).isdigit() else status


def get_result_message(result: dict) -> str:
    return str(result.get("msg") or result.get("message") or result.get("error") or "")


def is_rate_limited(result: dict) -> bool:
    status_code = get_status_code(result)
    msg = get_result_message(result).lower()
    return status_code in (402, 403, 429) or "ban" in msg or "rate" in msg


def get_retry_after(result: dict):
    return result.get("retry_after", "?")


def parse_eps_dataframe(result: dict) -> pd.DataFrame:
    df = pd.DataFrame(result.get("data") or [])
    df = df[df["type"] == "EPS"].copy()
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"])
    df["eps"] = pd.to_numeric(df["value"], errors="coerce")
    return df[["date", "eps"]].sort_values("date").reset_index(drop=True)


def parse_price_dataframe(result: dict) -> pd.DataFrame:
    df = pd.DataFrame(result.get("data") or [])
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df

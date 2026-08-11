import pandas as pd
import requests
import time

from data_layer.app_common import FINMIND_URL


def _result_payload(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        return payload
    return {}


def fetch_finmind_result(params: dict, timeout: int = 20) -> dict:
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.get(FINMIND_URL, params=params, timeout=timeout)
            result = _result_payload(resp)
            if not result and resp.status_code >= 400:
                result = {"status": resp.status_code, "msg": getattr(resp, "text", "")}
            if resp.status_code in (402, 403, 429) or is_rate_limited(result):
                return result
            if resp.status_code >= 400:
                resp.raise_for_status()
            return result
        except Exception as exc:
            last_exc = exc
            time.sleep(1.2 * (attempt + 1))
    raise last_exc


def get_status_code(result: dict):
    status = result.get("status")
    return int(status) if str(status).isdigit() else status


def get_result_message(result: dict) -> str:
    return str(result.get("msg") or result.get("message") or result.get("error") or "")


def is_rate_limited(result: dict) -> bool:
    status_code = get_status_code(result)
    msg = get_result_message(result).lower()
    return status_code in (402, 403, 429) or "ban" in msg or "rate" in msg or "limit" in msg


def get_retry_after(result: dict):
    return result.get("retry_after", "?")


def parse_price_dataframe(result: dict) -> pd.DataFrame:
    df = pd.DataFrame(result.get("data") or [])
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def fetch_finmind_price_frame(
    symbol: str,
    start_date: str,
    end_date: str,
    token: str = "",
    timeout: int = 30,
    sleep_seconds: float = 1.2,
    raise_on_rate_limit: bool = False,
) -> tuple[pd.DataFrame, int | None, str, object]:
    start_text = str(start_date).strip()
    end_text = str(end_date).strip()
    if not start_text or not end_text:
        raise ValueError("FinMind historical price requires start_date and end_date")

    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": str(symbol).strip(),
        "start_date": start_text,
        "end_date": end_text,
    }
    if token:
        params["token"] = token

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    result = fetch_finmind_result(params, timeout=timeout)
    status_code = get_status_code(result)
    msg = get_result_message(result)
    retry_after = get_retry_after(result)

    if is_rate_limited(result):
        if raise_on_rate_limit:
            raise RuntimeError(f"FINMIND_LIMIT:{status_code}:{retry_after}:{msg}")
        return pd.DataFrame(), status_code, msg, retry_after
    if status_code != 200 or not result.get("data"):
        return pd.DataFrame(), status_code, msg, retry_after

    df = parse_price_dataframe(result)
    if df.empty:
        return pd.DataFrame(), status_code, msg, retry_after

    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df, status_code, msg, retry_after

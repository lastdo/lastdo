from datetime import timedelta
import re
import time

import requests
import urllib3

from data_layer.time_utils import taipei_today


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Connection": "close",
}
URL_TWSE_MI_INDEX = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date}&type=ALLBUT0999"

TWSE_MI_INDEX_FIELDS = {
    "code": "\u8b49\u5238\u4ee3\u865f",
    "name": "\u8b49\u5238\u540d\u7a31",
    "volume": "\u6210\u4ea4\u80a1\u6578",
    "close": "\u6536\u76e4\u50f9",
    "sign": "\u6f32\u8dcc(+/-)",
    "change": "\u6f32\u8dcc\u50f9\u5dee",
}


def fetch_json_twse(url: str) -> list:
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=30, headers=DEFAULT_HEADERS)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise last_err


def _get_tpex_json(url: str):
    last_err = None
    for verify_ssl in (True, False):
        try:
            resp = requests.get(
                url,
                timeout=90,
                headers=DEFAULT_HEADERS,
                stream=False,
                verify=verify_ssl,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.SSLError as exc:
            last_err = exc
            if verify_ssl:
                continue
            raise
        except Exception as exc:
            last_err = exc
            break
    if last_err is not None:
        raise last_err
    return []


def fetch_json_tpex(url: str):
    last_err = None
    for attempt in range(3):
        try:
            return _get_tpex_json(url)
        except Exception as exc:
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise last_err


def _parse_market_number(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "---", "----", "X"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _twse_mi_index_change(sign_value, change_value):
    amount = _parse_market_number(change_value)
    if amount is None:
        return None
    sign_text = re.sub(r"<[^>]+>", "", str(sign_value or "")).strip()
    sign_raw = str(sign_value or "").lower()
    if "-" in sign_text or "green" in sign_raw:
        return -amount
    if "+" in sign_text or "red" in sign_raw:
        return amount
    return 0.0 if amount == 0 else amount


def _date_candidates(days: int = 7) -> list[str]:
    today = taipei_today()
    return [(today - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days)]


def parse_twse_mi_index_price_rows(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return []

    price_date = str(payload.get("date") or "").strip()
    for table in payload.get("tables") or []:
        fields = table.get("fields") or []
        required = [
            TWSE_MI_INDEX_FIELDS["code"],
            TWSE_MI_INDEX_FIELDS["name"],
            TWSE_MI_INDEX_FIELDS["close"],
        ]
        if not set(required).issubset(fields):
            continue

        idx_code = fields.index(TWSE_MI_INDEX_FIELDS["code"])
        idx_name = fields.index(TWSE_MI_INDEX_FIELDS["name"])
        idx_close = fields.index(TWSE_MI_INDEX_FIELDS["close"])
        idx_volume = fields.index(TWSE_MI_INDEX_FIELDS["volume"]) if TWSE_MI_INDEX_FIELDS["volume"] in fields else None
        idx_sign = fields.index(TWSE_MI_INDEX_FIELDS["sign"]) if TWSE_MI_INDEX_FIELDS["sign"] in fields else None
        idx_change = fields.index(TWSE_MI_INDEX_FIELDS["change"]) if TWSE_MI_INDEX_FIELDS["change"] in fields else None

        rows = []
        for values in table.get("data") or []:
            if not isinstance(values, list) or len(values) <= max(idx_code, idx_name, idx_close):
                continue
            close_price = _parse_market_number(values[idx_close])
            if close_price is None:
                continue

            change_value = (
                _twse_mi_index_change(values[idx_sign], values[idx_change])
                if idx_sign is not None and idx_change is not None and len(values) > max(idx_sign, idx_change)
                else None
            )
            rows.append(
                {
                    "Code": str(values[idx_code]).strip(),
                    "Name": str(values[idx_name]).strip(),
                    "ClosingPrice": values[idx_close],
                    "TradeVolume": values[idx_volume] if idx_volume is not None and len(values) > idx_volume else "0",
                    "Change": change_value,
                    "Date": price_date,
                }
            )
        return rows

    return []


def fetch_latest_twse_price_rows(_url: str | None = None) -> list:
    last_err = None
    for date_token in _date_candidates():
        try:
            rows = parse_twse_mi_index_price_rows(fetch_json_twse(URL_TWSE_MI_INDEX.format(date=date_token)))
            if rows:
                return rows
        except Exception as exc:
            last_err = exc
    if last_err is not None:
        raise last_err
    return []

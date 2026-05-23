import time

import requests


DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_json_twse(url: str) -> list:
    resp = requests.get(url, timeout=30, headers=DEFAULT_HEADERS)
    resp.raise_for_status()
    return resp.json()


def fetch_json_tpex(url: str) -> list:
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=90, headers=DEFAULT_HEADERS, stream=False)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise last_err

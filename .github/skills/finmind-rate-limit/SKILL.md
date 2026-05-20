---
name: finmind-rate-limit
description: 'Use when: building, modifying, reviewing, or debugging Python/Streamlit stock strategies that call FinMind, FinMind TaiwanStockFinancialStatements, EPS, financial statements, PE calculations, stock screeners, strategy screeners, or when errors mention rate limit, retry_after, ip banned, 402, 403, 429, API quota, token, or empty FinMind data. Ensures code avoids FinMind blocking and displays actionable retry timing.'
argument-hint: 'FinMind strategy, endpoint, or screener to check'
---

# FinMind Rate Limit Safety

Use this skill whenever a strategy, screener, page, test script, or helper function calls FinMind or depends on FinMind-derived data such as EPS, financial statements, PE ratio, revenue, or institutional/stock datasets.

## Goal

Prevent FinMind from blocking the user during normal strategy runs, and make blocking states actionable when they still happen.

The expected outcome is not just fewer API calls. The app should clearly tell the user whether FinMind was used, how many requests were planned/completed, whether rate limiting occurred, and exactly when the user can retry.

## Required Checks

1. Search for FinMind usage before editing.
   - Look for `api.finmindtrade.com`, `FINMIND_URL`, `FinMind`, `TaiwanStockFinancialStatements`, `token`, `retry_after`, `ip banned`, `status == 403`, `429`, and `ThreadPoolExecutor`.
   - Check both the target page and any test scripts that reproduce the issue.

2. Reduce candidate count before calling FinMind.
   - Apply all free/local filters first: price, revenue, volume, market, dates, chips, official TWSE/TPEX data, cached files, or user-provided portfolio constraints.
   - If the strategy only needs PE thresholding, prefer official TWSE/TPEX PE data as a loose prefilter before FinMind EPS calculation.
   - Do not send a broad universe of stocks directly to FinMind.

3. Avoid parallel FinMind calls by default.
   - Do not use `ThreadPoolExecutor`, async fan-out, or multiple workers for FinMind unless the user explicitly accepts blocking risk.
   - Use sequential calls with a visible progress indicator.
   - Keep a delay between calls. Start with at least `2.0` to `2.5` seconds for free-tier safety.

4. Cap FinMind work.
   - Add a maximum FinMind candidate count when the upstream candidate list can grow large.
   - Sort candidates by the strategy's strongest priority before truncating, so the cap keeps the most relevant stocks.
   - Show the user when a cap is applied: original count, capped count, and sorting basis.

5. Handle rate-limit responses explicitly.
   - Treat HTTP/status `402`, `403`, `429`, `ip banned`, `ban`, `rate`, and quota messages as rate-limit states.
   - Parse `retry_after` when present.
   - Do not silently convert rate-limit responses into empty DataFrames that later look like no matching stocks.
   - Raise or return a structured error for rate-limit states so the UI can stop or warn clearly.

6. Display actionable retry timing.
   - Show remaining wait time in human form, such as `12 分 34 秒`.
   - Show estimated local retry time, such as `15:42:10`.
   - Show whether the run completed zero FinMind calls or only a partial subset.
   - If `retry_after` is missing, say the wait time is unknown instead of inventing a number.

7. Be careful with caching.
   - Cache successful FinMind responses with a reasonable TTL.
   - Do not cache rate-limit failures as empty data.
   - If using Streamlit `@st.cache_data`, raise on rate-limit before returning an empty DataFrame.
   - Provide or respect a clear cache button when debugging API freshness.

8. Preserve strategy correctness.
   - If FinMind is the authoritative calculation source, use official/free APIs only as a prefilter, not as the final result unless the user approves.
   - If fallback results are shown after a partial FinMind failure, label them clearly as incomplete.
   - Do not let API failure masquerade as a valid empty result set.

## Recommended Helper Pattern

Use a small shared pattern in Python pages or utilities:

```python
def parse_finmind_retry_seconds(error_msg: str):
    parts = str(error_msg).split(":", 2)
    if len(parts) < 2:
        return None
    try:
        return max(int(float(parts[1])), 0)
    except Exception:
        return None


def format_wait_time(seconds):
    if seconds is None:
        return "未知"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours} 小時 {minutes} 分 {sec} 秒"
    if minutes > 0:
        return f"{minutes} 分 {sec} 秒"
    return f"{sec} 秒"


def format_retry_at(seconds):
    if seconds is None:
        return "未知"
    retry_at = datetime.now() + timedelta(seconds=int(seconds))
    return retry_at.strftime("%H:%M:%S")
```

When building a FinMind request function, use this style:

```python
result = resp.json()
status = result.get("status")
msg = str(result.get("msg") or result.get("message") or result.get("error") or "")
status_code = int(status) if str(status).isdigit() else status

if status_code in (402, 403, 429) or "ban" in msg.lower() or "rate" in msg.lower():
    raise RuntimeError(f"FINMIND_BANNED:{result.get('retry_after', '?')}:{msg}")

if status_code != 200 or not result.get("data"):
    raise RuntimeError(f"FINMIND_ERROR:{status}:{msg}")
```

## Streamlit UI Expectations

For a full block before any useful result:

```python
_retry_seconds = parse_finmind_retry_seconds(_banned_msg)
st.error(
    f"FinMind API 回傳 IP 暫時封鎖。\n\n"
    f"剩餘等待時間：約 **{format_wait_time(_retry_seconds)}**\n\n"
    f"預估可重新查詢時間：**{format_retry_at(_retry_seconds)}**"
)
st.stop()
```

For a partial block after some results:

```python
st.warning(
    f"FinMind API 中途被 rate limit，僅完成 {completed} / {planned} 檔，結果可能不完整。"
    f"剩餘等待時間：約 **{format_wait_time(_retry_seconds)}**；"
    f"預估可重新查詢時間：**{format_retry_at(_retry_seconds)}**。"
)
```

## Review Checklist

Before finishing a FinMind-related change, verify:

- Free filters run before FinMind.
- The number of planned FinMind calls is visible or easy to infer.
- There is no uncontrolled parallel FinMind fan-out.
- Rate-limit responses are not cached as empty data.
- `retry_after` is parsed from the correct field and not from the wrong `split()` segment.
- UI shows remaining wait time and estimated retry clock time.
- Partial results are clearly marked incomplete.
- Syntax checks pass for edited Python files.

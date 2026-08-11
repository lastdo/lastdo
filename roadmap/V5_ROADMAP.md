# V5 Roadmap

## Scope

V5 focuses on the two optimization tracks that are worth doing next:

- Large file decomposition.
- Shared FinMind historical price service.

Out of scope for this pass:

- Cross-screener UI extraction. Helpers such as watchlist adders, result view selectors, or page-specific table renderers stay inside each screener page for now.

## Track A: Large File Decomposition

Goal: reduce the risk of touching very large Streamlit modules by moving stable, page-agnostic pieces into smaller modules.

Phase A1:

- Move global navigation out of `render_layer/style.py` into `render_layer/navigation.py`.
- Keep the public import path `from render_layer.style import render_global_navigation` working while the rest of the app catches up.
- Add release guardrails so the navigation entries for stock screeners stay covered.

Phase A2:

- Split dashboard-only render helpers from `Inventory.py` when a future change touches that page.
- Keep data loading, rendering, and session-state mutation in separate sections or modules.

Phase A3:

- Split the AI analysis page into prompt/report/data helpers when working on report behavior again.
- Avoid broad rewrites; extract only stable helpers with tests or compile guardrails.

Acceptance:

- Existing pages still compile.
- Global navigation still exposes `法人重壓股` and `底部剛起漲`.
- No page-specific UI behavior is changed during decomposition.

## Track B: FinMind Historical Price Service

Goal: make historical price fetching consistent across screener pages so caching, rate-limit handling, and normalized columns stay in one place.

Phase B1:

- Add a shared service in `data_layer/historical_price_service.py`.
- Centralize cached calls to `fetch_finmind_price_frame`.
- Provide a small cleaning helper for sorted, non-empty price history frames.

Phase B2:

- Update growth, institutional-flow, and bottom-rebound screeners to use the shared service.
- Preserve each page's current rate-limit behavior and chart calculations.

Phase B3:

- Review backtest data sources for the same service shape after the screener pages stabilize.
- Keep backtest-specific storage/cache behavior separate unless the contracts are truly identical.

Acceptance:

- Historical price fetches share one cached FinMind access path in screener pages.
- Rate-limit errors remain recognizable as `FINMIND_LIMIT`.
- Touched Python files pass `python -m py_compile`, and the release guardrail tests pass.

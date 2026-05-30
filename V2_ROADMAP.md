# V2 Roadmap

## Current Assessment

The current system is a mature `v1` rather than a temporary prototype.

What is already working well:

- The product has a clear main workflow: screening, analysis, history, and portfolio/watchlist management.
- The UI already has recognizable product structure instead of looking like a loose collection of pages.
- The shared code has started to separate into `data_layer` and `render_layer`, which is a healthy direction.
- Core Taiwan stock data integrations are already useful in real usage.

What keeps it from being a fully mature long-term system:

- External data reliability is still a major dependency risk.
- Core module contracts are not yet strict enough.
- Regression safety mainly depends on manual checking.
- Some page files still carry too much orchestration and display preparation logic.

In short:

`v1` is already solid enough to be considered a serious working product.
`v2` should focus on reliability, maintainability, and workflow depth rather than only adding more features.

## V2 Priorities

### 1. Data Reliability and Observability

Goal:
Make the system honest and resilient when upstream data is incomplete, delayed, rate-limited, or structurally changed.

Work items:

- Add clearer status reporting for TWSE, TPEX, FinMind, and news fetches.
- Distinguish between complete data, partial data, stale cache, and failed fetch.
- Add stronger retry and fallback handling where appropriate.
- Show page-level health hints when a result is incomplete rather than silently degrading.
- Centralize source diagnostics so each page does not invent its own warning style.

Why this matters:

This is the biggest current product risk. A stock app becomes hard to trust if users cannot tell whether the data is truly current and complete.

### 2. Data Layer Contracts

Goal:
Make `data_layer` predictable enough that future page changes do not break from hidden assumptions.

Work items:

- Standardize return schemas for shared helpers.
- Document required and optional fields for key outputs.
- Normalize naming for repeated concepts such as `stock_id`, `latest_price`, `price_date`, `vol_lot`, `unrealized_pnl`.
- Reduce page-specific assumptions about raw helper outputs.
- Add a lightweight convention document for shared data contracts.

Why this matters:

The current reorganization into `data_layer` is the right start. The next maturity step is making those modules reliable contracts, not just relocated files.

### 3. Test Coverage for Core Flows

Goal:
Protect the most important business logic from regressions.

Recommended first tests:

- Market data parsing tests for TWSE and TPEX payloads.
- Portfolio load/update/delete behavior tests.
- Family ID filtering tests.
- Inventory table preparation tests.
- Edge case tests for missing prices, missing fields, empty datasets, and rate-limit responses.

Why this matters:

Right now most confidence still comes from manual validation. That works for a while, but `v2` needs a safer base if features keep growing.

### 4. Page Logic Simplification

Goal:
Reduce the amount of mixed concerns inside large Streamlit pages.

Work items:

- Move table-preparation logic out of page files where practical.
- Move repeated “result summary / diagnostics / empty state” assembly into shared render patterns.
- Keep pages focused on orchestration and user interaction.
- Continue tightening the line between `data_layer` and `render_layer`.

Why this matters:

Several pages are already feature-rich. Without continued simplification, future changes will become slower and riskier.

### 5. Mobile Experience

Goal:
Make the product genuinely usable on smaller screens rather than merely viewable.

Key targets:

- Sidebar ergonomics
- Summary card stacking
- Table overflow behavior
- Action area readability
- Screen hierarchy and spacing on phone widths

Why this matters:

This is the most visible UX gap left in the current product.

### 6. Workflow Integration

Goal:
Turn the app from “several strong tools” into one connected operating flow.

Work items:

- Better handoff from screener results to analysis pages.
- Better handoff from analysis pages to watchlist / holdings.
- Make analysis history more visible from watchlist and holdings.
- Improve “what should I review next?” entry points inside the inventory dashboard.

Why this matters:

This is where product maturity starts to feel substantial to end users, not just technically improved.

## Suggested Delivery Phases

### Short Term

- Data fetch diagnostics
- Core parsing and portfolio tests
- Mobile fixes for the inventory page
- Small page logic extractions where risk is low

### Mid Term

- Stronger data contracts across `data_layer`
- Shared result and diagnostics rendering patterns
- Workflow links between screeners, analysis, and inventory
- Expanded tests for key pages

### Long Term

- Broader consistency across all pages
- More advanced portfolio insight views
- Better system health / admin visibility
- Larger product-level expansion after the foundation is stable

## Recommended V2 Order

1. Data reliability and diagnostics
2. Core tests
3. Data layer contract cleanup
4. Mobile optimization
5. Workflow integration

## Final Direction

`v2` should not try to become “more impressive” first.

It should become:

- more trustworthy
- easier to maintain
- safer to extend
- more coherent as one product

That is the path from a strong `v1` into a genuinely durable system.

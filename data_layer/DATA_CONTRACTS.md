# Data Layer Contracts

This document defines the stable output schemas used by Streamlit pages.
When a helper changes one of these fields, update this document and the matching
contract in `data_layer/contracts.py` in the same change.

## Naming Rules

- Use `stock_id` for normalized Taiwan stock code joins.
- Use `stock_name` for normalized display names.
- Use `close` for the latest official close price in screening dataframes.
- Use `latest_price` only for portfolio/inventory market snapshots.
- Use `price_date` for the source date of an inventory market quote.
- Use `vol_lot` for trading volume in lots.
- Use `unrealized_pnl` for net unrealized P/L after estimated sell costs.

## Market Dataframes

### `price_snapshot`

Produced by `build_price_snapshot`.

Required columns:

- `stock_id`: string stock code.
- `stock_name`: string display name.
- `market`: `TWSE` or `TPEX`.
- `close`: numeric latest close.
- `vol_lot`: numeric trading volume in lots.

### `revenue_snapshot`

Produced by `build_revenue_snapshot`.

Required columns:

- `stock_id`: string stock code.
- `rev_ym`: ROC year/month string normalized without `/`.
- `rev_cur`: numeric current monthly revenue.
- `rev_ly`: numeric revenue for the same month last year.
- `rev_yoy`: numeric year-over-year revenue growth percentage.

### `recent_revenue_metrics`

Produced by `build_recent_revenue_metrics`.

Required columns:

- All `revenue_snapshot` columns.
- `avg_rev_yoy`: numeric average YoY over the selected recent months.
- `rev_months`: string list of included months.
- `latest_rev_yoy`: latest month YoY.
- `prev_rev_yoy`: previous included month YoY, nullable.

## Valuation Dataframes

### `public_pe`

Produced by `build_public_pe_snapshot` and `fetch_public_pe_ratios`.

Required columns:

- `stock_id`: string stock code.
- `pe_ratio_public`: numeric official PE ratio from TWSE/TPEX.

### `public_valuation`

Produced by `attach_public_valuation`.

Required columns:

- `stock_id`
- `pe_ratio_public`
- `pe_ratio`
- `ttm_eps`
- `pe_label`

## Institutional Flow Dataframes

### `institutional_net_buy`

Produced by `build_institutional_net_buy_frame`.

Required columns:

- `stock_id`: string stock code.
- `foreign_net_shares`: numeric net foreign buy/sell shares.

## Portfolio Items

Produced by `normalize_portfolio_item`, `load_portfolio`, and `create_portfolio_item`.

Required keys:

- `row_id`
- `family_id`
- `symbol`
- `stock_id`
- `stock_name`
- `name`
- `price`
- `avg_cost`
- `shares`
- `note`
- `created_at`
- `updated_at`
- `is_deleted`

Compatibility aliases:

- `symbol` mirrors `stock_id`.
- `name` mirrors `stock_name`.
- `price` mirrors `avg_cost`.


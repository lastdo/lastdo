from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DataFrameContract:
    name: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()

    @property
    def columns(self) -> tuple[str, ...]:
        return self.required + self.optional


PRICE_SNAPSHOT_CONTRACT = DataFrameContract(
    name="price_snapshot",
    required=("stock_id", "stock_name", "market", "close", "vol_lot"),
)

REVENUE_SNAPSHOT_CONTRACT = DataFrameContract(
    name="revenue_snapshot",
    required=("stock_id", "rev_ym", "rev_cur", "rev_ly", "rev_yoy"),
)

RECENT_REVENUE_METRICS_CONTRACT = DataFrameContract(
    name="recent_revenue_metrics",
    required=(
        "stock_id",
        "rev_ym",
        "rev_cur",
        "rev_ly",
        "rev_yoy",
        "avg_rev_yoy",
        "rev_months",
        "latest_rev_yoy",
        "prev_rev_yoy",
    ),
)

PUBLIC_PE_CONTRACT = DataFrameContract(
    name="public_pe",
    required=("stock_id", "pe_ratio_public"),
)

PUBLIC_VALUATION_CONTRACT = DataFrameContract(
    name="public_valuation",
    required=("stock_id", "pe_ratio_public", "pe_ratio", "ttm_eps", "pe_label"),
)

INSTITUTIONAL_NET_BUY_CONTRACT = DataFrameContract(
    name="institutional_net_buy",
    required=("stock_id", "foreign_net_shares"),
)

PORTFOLIO_ITEM_FIELDS = (
    "row_id",
    "family_id",
    "symbol",
    "stock_id",
    "stock_name",
    "name",
    "price",
    "avg_cost",
    "shares",
    "note",
    "created_at",
    "updated_at",
    "is_deleted",
)


def empty_contract_frame(contract: DataFrameContract) -> pd.DataFrame:
    return pd.DataFrame(columns=list(contract.columns))


def missing_required_columns(df: pd.DataFrame, contract: DataFrameContract) -> list[str]:
    return [column for column in contract.required if column not in df.columns]


def ensure_dataframe_contract(df: pd.DataFrame, contract: DataFrameContract) -> pd.DataFrame:
    missing = missing_required_columns(df, contract)
    if missing:
        raise ValueError(f"{contract.name} missing required columns: {', '.join(missing)}")
    return df


def select_contract_columns(df: pd.DataFrame, contract: DataFrameContract) -> pd.DataFrame:
    ensure_dataframe_contract(df, contract)
    return df[[column for column in contract.columns if column in df.columns]]


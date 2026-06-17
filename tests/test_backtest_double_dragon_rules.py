from datetime import date
from unittest.mock import patch

import pandas as pd

from backtest_common.double_dragon_rules import (
    apply_double_dragon_flags,
    calc_ttm_eps,
    latest_complete_revenue_ym,
    price_window_start,
)
from backtest_data_layer.double_dragon_snapshot import load_candidate_universe


def test_revenue_month_uses_generic_as_of_date():
    assert latest_complete_revenue_ym(date(2026, 3, 18)) == "11502"
    assert latest_complete_revenue_ym(date(2026, 6, 18)) == "11505"


def test_price_window_is_relative_to_any_as_of_date():
    march_window = price_window_start(date(2026, 3, 18))
    june_window = price_window_start(date(2026, 6, 18))

    assert march_window < date(2026, 3, 18)
    assert june_window < date(2026, 6, 18)
    assert (june_window - march_window).days == 92


def test_calc_ttm_eps_ignores_future_quarters():
    df = pd.DataFrame(
        {
            "date": [
                "2025-03-31",
                "2025-06-30",
                "2025-09-30",
                "2025-12-31",
                "2026-03-31",
            ],
            "type": ["EPS", "EPS", "EPS", "EPS", "EPS"],
            "value": [1.0, 1.5, 2.0, 2.5, 99.0],
        }
    )

    result = calc_ttm_eps(df, date(2026, 3, 18))

    assert result["ttm_eps"] == 7.0
    assert result["eps_quarters"] == "2025-03-31/2025-06-30/2025-09-30/2025-12-31"


def test_double_dragon_flags_are_data_driven_not_date_driven():
    df = pd.DataFrame(
        {
            "stock_id": ["1111", "2222"],
            "close": [130.0, 110.0],
            "vol_lot": [1500.0, 1600.0],
            "avg_rev_yoy": [25.0, 30.0],
            "ttm_eps": [10.0, 8.0],
            "pe_ratio": [13.0, 13.75],
            "ma60": [120.0, 130.0],
            "six_month_low": [100.0, 100.0],
        }
    )

    result = apply_double_dragon_flags(df)

    assert result.loc[0, "is_dragon_rise_pass"]
    assert not result.loc[0, "is_dragon_hidden_pass"]
    assert not result.loc[1, "is_dragon_rise_pass"]
    assert result.loc[1, "is_dragon_hidden_pass"]


def test_candidate_universe_filters_price_volume_before_revenue_join():
    price_df = pd.DataFrame(
        {
            "stock_id": ["1111", "2222", "3333"],
            "stock_name": ["A", "B", "C"],
            "market": ["TWSE", "TWSE", "TPEX"],
            "price_date": ["2026-03-18", "2026-03-18", "2026-03-18"],
            "close": [80.0, 50.0, 90.0],
            "vol_lot": [1200.0, 2000.0, 500.0],
        }
    )
    revenue_df = pd.DataFrame(
        {
            "stock_id": ["1111", "2222", "3333"],
            "rev_ym": ["11501", "11501", "11501"],
            "rev_yoy": [30.0, 30.0, 30.0],
            "rev_cur": [100, 100, 100],
            "rev_ly": [80, 80, 80],
            "avg_rev_yoy": [30.0, 30.0, 30.0],
            "rev_months": ["11501/11412", "11501/11412", "11501/11412"],
            "latest_rev_yoy": [30.0, 30.0, 30.0],
            "prev_rev_yoy": [30.0, 30.0, 30.0],
        }
    )

    with patch("backtest_data_layer.double_dragon_snapshot.fetch_historical_price_snapshot", return_value=price_df):
        with patch("backtest_data_layer.double_dragon_snapshot.load_revenue_candidates", return_value=(revenue_df, "11502", 3)):
            universe, diagnostics = load_candidate_universe(date(2026, 3, 18))

    assert universe["stock_id"].tolist() == ["1111"]
    assert diagnostics.price_rows == 3
    assert diagnostics.price_volume_candidates == 1
    assert diagnostics.revenue_candidates == 1

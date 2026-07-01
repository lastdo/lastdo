from datetime import date
from unittest.mock import patch

import pandas as pd

from backtest_common.double_dragon_rules import (
    apply_double_dragon_flags,
    calc_ttm_eps,
    latest_complete_revenue_ym,
    price_window_start,
)
from backtest_data_layer.double_dragon_snapshot import (
    SnapshotDiagnostics,
    build_double_dragon_snapshot,
    load_candidate_universe,
    load_revenue_candidates,
)
from backtest_render_layer.double_dragon_tables import DISPLAY_COLUMNS


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
            "ma240": [110.0, 100.0],
            "six_month_low": [100.0, 100.0],
        }
    )

    result = apply_double_dragon_flags(df)

    assert result.loc[0, "is_dragon_rise_pass"]
    assert not result.loc[0, "is_dragon_hidden_pass"]
    assert not result.loc[1, "is_dragon_rise_pass"]
    assert result.loc[1, "is_dragon_hidden_pass"]


def test_dragon_rise_requires_price_within_year_line_premium():
    df = pd.DataFrame(
        {
            "stock_id": ["1111"],
            "close": [150.0],
            "vol_lot": [1500.0],
            "avg_rev_yoy": [25.0],
            "ttm_eps": [10.0],
            "pe_ratio": [15.0],
            "ma60": [120.0],
            "ma240": [100.0],
            "six_month_low": [100.0],
        }
    )

    result = apply_double_dragon_flags(df)

    assert result.loc[0, "is_common_pass"]
    assert not result.loc[0, "is_dragon_rise_pass"]


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


def test_revenue_candidates_report_resolved_mops_month():
    revenue_raw = pd.DataFrame(
        {
            "stock_id": ["1111", "1111"],
            "rev_ym": ["11505", "11504"],
            "rev_yoy": [30.0, 25.0],
            "rev_cur": [100, 100],
            "rev_ly": [80, 80],
        }
    )
    revenue_raw.attrs["resolved_latest_ym"] = "11505"
    revenue_raw.attrs["selected_rev_months"] = ("11505", "11504")
    revenue_raw.attrs["skipped_incomplete_rev_months"] = ("11506",)

    with patch("backtest_data_layer.double_dragon_snapshot.fetch_mops_recent_revenue_frame", return_value=revenue_raw):
        candidates, revenue_month, revenue_rows = load_revenue_candidates(date(2026, 7, 1))

    assert revenue_month == "11505"
    assert revenue_rows == 2
    assert candidates["rev_months"].tolist() == ["11505/11504"]


def test_revenue_candidates_use_latest_two_months_per_stock():
    revenue_raw = pd.DataFrame(
        {
            "stock_id": ["1111", "1111", "2222", "2222"],
            "rev_ym": ["11506", "11505", "11505", "11504"],
            "rev_yoy": [30.0, 25.0, 28.0, 24.0],
            "rev_cur": [100, 100, 100, 100],
            "rev_ly": [80, 80, 80, 80],
        }
    )
    revenue_raw.attrs["resolved_latest_ym"] = "11506"
    revenue_raw.attrs["selected_rev_months"] = ("11506", "11505", "11504")
    revenue_raw.attrs["complete_rev_months"] = ("11505", "11504")
    revenue_raw.attrs["skipped_incomplete_rev_months"] = ("11506",)

    with patch("backtest_data_layer.double_dragon_snapshot.fetch_mops_recent_revenue_frame", return_value=revenue_raw):
        candidates, revenue_month, revenue_rows = load_revenue_candidates(date(2026, 7, 1))

    by_stock = candidates.set_index("stock_id")
    assert revenue_month == "11506"
    assert revenue_rows == 4
    assert by_stock.loc["1111", "rev_months"] == "11506/11505"
    assert by_stock.loc["2222", "rev_months"] == "11505/11504"


def test_snapshot_returns_only_common_passed_rows():
    universe = pd.DataFrame(
        {
            "stock_id": ["1111", "2222"],
            "stock_name": ["A", "B"],
            "market": ["TWSE", "TWSE"],
            "close": [120.0, 120.0],
            "vol_lot": [1500.0, 1500.0],
            "price_date": ["2026-03-18", "2026-03-18"],
            "avg_rev_yoy": [30.0, 30.0],
            "rev_months": ["11501/11412", "11501/11412"],
            "rev_ym": ["11501", "11501"],
            "rev_yoy": [30.0, 30.0],
            "rev_cur": [100, 100],
            "rev_ly": [80, 80],
            "latest_rev_yoy": [30.0, 30.0],
            "prev_rev_yoy": [30.0, 30.0],
        }
    )
    diagnostics = SnapshotDiagnostics(
        stock_count=2,
        price_rows=2,
        price_volume_candidates=2,
        revenue_month_start="11502",
        revenue_rows=2,
        revenue_candidates=2,
        common_passed=0,
        common_failed=0,
        processed=0,
        price_failed=(),
        eps_failed=(),
    )

    def fake_build(row, as_of_date, token):
        eps = 6.0 if row["stock_id"] == "1111" else 4.0
        return (
            "ok",
            {
                "as_of_date": "2026-03-18",
                "stock_id": row["stock_id"],
                "stock_name": row["stock_name"],
                "market": row["market"],
                "price_date": row["price_date"],
                "close": row["close"],
                "vol_lot": row["vol_lot"],
                "ma60": 100.0,
                "ma240": 100.0,
                "six_month_low": 100.0,
                "six_month_low_date": "2026-01-01",
                "ma60_premium_pct": 20.0,
                "ma240_premium_pct": 20.0,
                "low_premium_pct": 20.0,
                "history_days": 120,
                "avg_rev_yoy": row["avg_rev_yoy"],
                "rev_months": row["rev_months"],
                "ttm_eps": eps,
                "eps_quarters": "q1/q2/q3/q4",
                "pe_ratio": row["close"] / eps,
            },
        )

    with patch("backtest_data_layer.double_dragon_snapshot.load_candidate_universe", return_value=(universe, diagnostics)):
        with patch("backtest_data_layer.double_dragon_snapshot._build_stock_snapshot", side_effect=fake_build):
            snapshot, result_diagnostics = build_double_dragon_snapshot(date(2026, 3, 18))

    assert snapshot["stock_id"].tolist() == ["1111"]
    assert snapshot.loc[0, "branch_label"] == "雙龍合璧"
    assert result_diagnostics.common_passed == 1
    assert result_diagnostics.common_failed == 1


def test_snapshot_surfaces_finmind_rate_limit_in_diagnostics():
    universe = pd.DataFrame(
        {
            "stock_id": ["1111"],
            "stock_name": ["A"],
            "market": ["TWSE"],
            "close": [120.0],
            "vol_lot": [1500.0],
            "price_date": ["2026-03-18"],
            "avg_rev_yoy": [30.0],
            "rev_months": ["11501/11412"],
            "rev_ym": ["11501"],
            "rev_yoy": [30.0],
            "rev_cur": [100],
            "rev_ly": [80],
            "latest_rev_yoy": [30.0],
            "prev_rev_yoy": [30.0],
        }
    )
    diagnostics = SnapshotDiagnostics(
        stock_count=1,
        price_rows=1,
        price_volume_candidates=1,
        revenue_month_start="11502",
        revenue_rows=1,
        revenue_candidates=1,
        common_passed=0,
        common_failed=0,
        processed=0,
        price_failed=(),
        eps_failed=(),
    )

    with patch("backtest_data_layer.double_dragon_snapshot.load_candidate_universe", return_value=(universe, diagnostics)):
        with patch(
            "backtest_data_layer.double_dragon_snapshot._build_stock_snapshot",
            side_effect=RuntimeError("FINMIND_LIMIT:402:60:Requests reach the upper limit."),
        ):
            snapshot, result_diagnostics = build_double_dragon_snapshot(date(2026, 3, 18))

    assert snapshot.empty
    assert result_diagnostics.processed == 1
    assert result_diagnostics.price_failed == ()
    assert result_diagnostics.rate_limit_error == "FINMIND_LIMIT:402:60:Requests reach the upper limit."


def test_display_columns_do_not_expose_internal_booleans():
    assert "is_common_pass" not in DISPLAY_COLUMNS
    assert "is_dragon_rise_pass" not in DISPLAY_COLUMNS
    assert "is_dragon_hidden_pass" not in DISPLAY_COLUMNS

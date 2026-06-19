from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from backtest_data_layer.performance import build_return_analysis


def test_build_return_analysis_calculates_stock_benchmark_and_excess_returns():
    snapshot = pd.DataFrame(
        {
            "stock_id": ["1111", "2222"],
            "stock_name": ["A", "B"],
            "branch_label": ["rise", "hidden"],
            "close": [100.0, 200.0],
            "price_date": ["2026-03-18", "2026-03-18"],
        }
    )

    histories = {
        "TAIEX": pd.DataFrame(
            {
                "date": ["2026-03-18", "2026-03-19", "2026-03-20"],
                "close": [10000.0, 10100.0, 10200.0],
            }
        ),
        "1111": pd.DataFrame(
            {
                "date": ["2026-03-18", "2026-03-19", "2026-03-20"],
                "close": [100.0, 110.0, 120.0],
            }
        ),
        "2222": pd.DataFrame(
            {
                "date": ["2026-03-18", "2026-03-19", "2026-03-20"],
                "close": [200.0, 190.0, 220.0],
            }
        ),
    }

    def fake_fetch(stock_id, start_date, end_date, token="", sleep_seconds=0):
        return histories[stock_id]

    with patch("backtest_data_layer.performance.fetch_price_history_frame", side_effect=fake_fetch):
        return_df, curve_df, kpis, diagnostics = build_return_analysis(
            snapshot,
            date(2026, 3, 18),
            date(2026, 3, 20),
        )

    assert diagnostics.requested_stocks == 2
    assert diagnostics.priced_stocks == 2
    assert diagnostics.benchmark_return_pct == pytest.approx(2.0)
    assert return_df.set_index("stock_id").loc["1111", "stock_return_pct"] == pytest.approx(20.0)
    assert return_df.set_index("stock_id").loc["2222", "stock_return_pct"] == pytest.approx(10.0)
    assert return_df.set_index("stock_id").loc["1111", "excess_return_pct"] == pytest.approx(18.0)
    assert kpis["portfolio_return_pct"] == pytest.approx(15.0)
    assert kpis["excess_return_pct"] == pytest.approx(13.0)
    assert set(["portfolio_return_pct", "benchmark_return_pct", "excess_return_pct"]).issubset(curve_df.columns)
    assert curve_df.iloc[-1]["portfolio_return_pct"] == pytest.approx(15.0)


def test_build_return_analysis_surfaces_failed_stock_without_false_zero():
    snapshot = pd.DataFrame(
        {
            "stock_id": ["1111", "2222"],
            "stock_name": ["A", "B"],
            "close": [100.0, 200.0],
        }
    )

    def fake_fetch(stock_id, start_date, end_date, token="", sleep_seconds=0):
        if stock_id == "TAIEX":
            return pd.DataFrame({"date": ["2026-03-18", "2026-03-20"], "close": [10000.0, 10100.0]})
        if stock_id == "1111":
            return pd.DataFrame({"date": ["2026-03-18", "2026-03-20"], "close": [100.0, 120.0]})
        return pd.DataFrame()

    with patch("backtest_data_layer.performance.fetch_price_history_frame", side_effect=fake_fetch):
        return_df, _curve_df, kpis, diagnostics = build_return_analysis(
            snapshot,
            date(2026, 3, 18),
            date(2026, 3, 20),
        )

    assert return_df["stock_id"].tolist() == ["1111"]
    assert diagnostics.requested_stocks == 2
    assert diagnostics.priced_stocks == 1
    assert diagnostics.failed_stocks == ("2222",)
    assert kpis["portfolio_return_pct"] == pytest.approx(20.0)

from unittest.mock import patch

import pandas as pd

from backtest_data_layer.double_dragon_snapshot import SnapshotDiagnostics
from backtest_data_layer.supabase_store import (
    load_backtest_snapshot,
    save_backtest_snapshot,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = "[]" if text is None else text

    def json(self):
        return self._payload


def _diagnostics():
    return SnapshotDiagnostics(
        stock_count=2,
        price_rows=2,
        price_volume_candidates=2,
        revenue_month_start="11505",
        revenue_rows=10,
        revenue_candidates=2,
        common_passed=1,
        common_failed=1,
        processed=2,
        price_failed=(),
        eps_failed=("2222",),
    )


def test_save_backtest_snapshot_posts_run_and_rows():
    calls = []

    def fake_request(method, endpoint, params=None, json=None, headers=None, timeout=None):
        calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "params": params,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeResponse(payload=[{"run_id": "stored"}])

    df = pd.DataFrame(
        {
            "stock_id": ["1111"],
            "branch_label": ["雙龍合璧"],
            "close": [120.0],
            "is_dragon_rise_pass": [True],
            "is_dragon_hidden_pass": [True],
            "ma240": [100.0],
        }
    )

    with patch("backtest_data_layer.supabase_store._supabase_config", return_value=("https://example.supabase.co", "token")):
        with patch("backtest_data_layer.supabase_store.requests.request", side_effect=fake_request):
            run_id = save_backtest_snapshot("2026-06-18", df, _diagnostics(), max_targets=50)

    assert run_id.startswith("double_dragon:2026-06-18:")
    assert calls[0]["endpoint"].endswith("/rest/v1/backtest_runs")
    assert calls[0]["json"]["as_of_date"] == "2026-06-18"
    assert calls[0]["json"]["combined_count"] == 1
    assert calls[0]["json"]["diagnostics"]["revenue_month_start"] == "11505"
    assert calls[1]["endpoint"].endswith("/rest/v1/backtest_snapshot_rows")
    assert calls[1]["json"][0]["payload"]["stock_id"] == "1111"
    assert calls[1]["headers"]["Authorization"] == "Bearer token"


def test_load_backtest_snapshot_rebuilds_dataframe_and_diagnostics():
    def fake_request(method, endpoint, params=None, json=None, headers=None, timeout=None):
        if endpoint.endswith("/rest/v1/backtest_runs"):
            return FakeResponse(
                payload=[
                    {
                        "run_id": "run-1",
                        "diagnostics": {
                            "stock_count": 2,
                            "price_rows": 2,
                            "price_volume_candidates": 2,
                            "revenue_month_start": "11505",
                            "revenue_rows": 10,
                            "revenue_candidates": 2,
                            "common_passed": 1,
                            "common_failed": 1,
                            "processed": 2,
                            "price_failed": [],
                            "eps_failed": ["2222"],
                        },
                    }
                ]
            )
        return FakeResponse(
            payload=[
                {"payload": {"stock_id": "1111", "close": 120.0, "branch_label": "雙龍合璧"}},
                {"payload": {"stock_id": "2222", "close": 80.0, "branch_label": "未進分支"}},
            ]
        )

    with patch("backtest_data_layer.supabase_store._supabase_config", return_value=("https://example.supabase.co", "token")):
        with patch("backtest_data_layer.supabase_store.requests.request", side_effect=fake_request):
            stored = load_backtest_snapshot("run-1")

    assert stored.run["run_id"] == "run-1"
    assert stored.snapshot["stock_id"].tolist() == ["1111", "2222"]
    assert stored.diagnostics.revenue_month_start == "11505"
    assert stored.diagnostics.eps_failed == ("2222",)

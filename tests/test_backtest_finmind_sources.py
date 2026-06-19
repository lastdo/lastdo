from unittest.mock import Mock, patch

import pytest
import requests

from backtest_data_layer.finmind_sources import fetch_finmind_dataset_frame


def test_fetch_finmind_dataset_frame_raises_finmind_limit_before_http_error():
    response = Mock()
    response.status_code = 402
    response.json.return_value = {
        "status": 402,
        "msg": "Requests reach the upper limit.",
        "retry_after": 60,
        "data": [],
    }
    response.raise_for_status.side_effect = requests.HTTPError("payment required")

    with patch("backtest_data_layer.finmind_sources.requests.get", return_value=response):
        with pytest.raises(RuntimeError, match=r"^FINMIND_LIMIT:402:60:Requests reach the upper limit\.$"):
            fetch_finmind_dataset_frame("TaiwanStockPrice", data_id="2330", sleep_seconds=0)

    response.raise_for_status.assert_not_called()

from unittest.mock import Mock, patch

import pytest
import requests

from data_layer.finmind_api import fetch_finmind_price_frame


def test_fetch_finmind_price_frame_preserves_http_402_rate_limit():
    response = Mock()
    response.status_code = 402
    response.json.return_value = {
        "status": 402,
        "msg": "Requests reach the upper limit.",
        "retry_after": 60,
        "data": [],
    }
    response.raise_for_status.side_effect = requests.HTTPError("payment required")

    with patch("data_layer.finmind_api.requests.get", return_value=response):
        df, status_code, msg, retry_after = fetch_finmind_price_frame(
            "2330",
            "2026-01-01",
            "2026-06-18",
            sleep_seconds=0,
            raise_on_rate_limit=False,
        )

    assert df.empty
    assert status_code == 402
    assert msg == "Requests reach the upper limit."
    assert retry_after == 60
    response.raise_for_status.assert_not_called()


def test_fetch_finmind_price_frame_can_raise_recognizable_limit_error():
    response = Mock()
    response.status_code = 402
    response.json.return_value = {
        "status": 402,
        "msg": "Requests reach the upper limit.",
        "retry_after": "?",
        "data": [],
    }

    with patch("data_layer.finmind_api.requests.get", return_value=response):
        with pytest.raises(RuntimeError, match=r"^FINMIND_LIMIT:402:\?:Requests reach the upper limit\.$"):
            fetch_finmind_price_frame(
                "2330",
                "2026-01-01",
                "2026-06-18",
                sleep_seconds=0,
                raise_on_rate_limit=True,
            )

import unittest
from unittest.mock import patch

import requests

from data_layer.market_api import _get_tpex_json, parse_json_response
from data_layer.institutional_flow import (
    _find_tpex_foreign_net_columns,
    fetch_tpex_3insti,
)


class MarketApiTpexTests(unittest.TestCase):
    def test_tpex_json_retries_without_ssl_verification(self):
        class FakeResponse:
            status_code = 200
            headers = {"content-type": "application/json"}
            text = '{"tables":[]}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"tables": [{"fields": [], "data": []}]}

        verify_values = []

        def fake_get(url, timeout=None, headers=None, stream=False, verify=True):
            verify_values.append(verify)
            if verify:
                raise requests.exceptions.SSLError("bad certificate")
            return FakeResponse()

        with patch("data_layer.market_api.requests.get", side_effect=fake_get):
            result = _get_tpex_json("https://www.tpex.org.tw/example")

        self.assertEqual(result, {"tables": [{"fields": [], "data": []}]})
        self.assertEqual(verify_values, [True, False])

    def test_parse_json_response_reports_html_body(self):
        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/html"}
            text = "<html>maintenance</html>"

            def json(self):
                raise ValueError("not json")

        with self.assertRaisesRegex(RuntimeError, "TWSE returned non-JSON response"):
            parse_json_response(FakeResponse(), "TWSE")

    def test_tpex_institutional_current_openapi_columns(self):
        columns = [
            "Date",
            "SecuritiesCompanyCode",
            "ForeignInvestorsInclude MainlandAreaInvestors-Difference",
            "ForeignDealers-Difference",
        ]

        self.assertEqual(
            _find_tpex_foreign_net_columns(columns),
            ("ForeignInvestorsInclude MainlandAreaInvestors-Difference", None),
        )

    def test_tpex_institutional_uses_current_openapi_only(self):
        payload = [
            {
                "Date": "1150622",
                "SecuritiesCompanyCode": "1234",
                "ForeignInvestorsInclude MainlandAreaInvestors-Difference": "3,500",
            }
        ]
        urls = []

        def fake_fetch(url):
            urls.append(url)
            return payload

        fetch_tpex_3insti.clear()
        with patch("data_layer.institutional_flow.fetch_json_tpex", side_effect=fake_fetch):
            df = fetch_tpex_3insti("115/06/19")
        fetch_tpex_3insti.clear()

        self.assertEqual(urls, ["https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"])
        self.assertEqual(df.to_dict("records"), [{"stock_id": "1234", "foreign_net_shares": 3500}])


if __name__ == "__main__":
    unittest.main()

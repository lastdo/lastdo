import unittest
from unittest.mock import patch

import pandas as pd

from data_layer import mops_revenue
from data_layer.contracts import (
    PRICE_SNAPSHOT_CONTRACT,
    PUBLIC_PE_CONTRACT,
    missing_required_columns,
)
from data_layer.market_data import (
    build_institutional_net_buy_frame,
    build_latest_revenue_view,
    build_price_snapshot,
    build_public_pe_snapshot,
    build_recent_revenue_metrics,
    build_revenue_snapshot,
)
from data_layer.market_api import parse_twse_mi_index_price_rows
from data_layer.public_valuation import attach_public_valuation


class MarketDataContractTests(unittest.TestCase):
    def test_fetch_mops_month_revenue_uses_direct_mops_fields(self):
        class FakeFetcher:
            def get_market_revenue(self, year, month, market, company_type):
                raise RuntimeError("HTTP 307")

        direct_rows = [
            {
                "stock_id": "2330",
                "company_name": "TSMC",
                "year": 115,
                "month": 5,
                "revenue": "300000",
                "revenue_last_year": "200000",
                "yoy_change": "50.0",
            }
        ]

        with patch("data_layer.mops_revenue.RevenueFetcher", return_value=FakeFetcher()):
            with patch(
                "data_layer.mops_revenue._fetch_market_revenue_with_redirects",
                return_value=direct_rows,
            ):
                df = mops_revenue.fetch_mops_month_revenue_frame(
                    115,
                    5,
                    markets=("sii",),
                    company_types=(0,),
                )

        self.assertEqual(df["stock_id"].tolist(), ["2330"])
        self.assertEqual(df.loc[0, "rev_ym"], "11505")
        self.assertEqual(df.loc[0, "rev_yoy"], 50.0)

    def test_parse_mops_revenue_tables_matches_current_mops_headers(self):
        columns = pd.MultiIndex.from_tuples(
            [
                ("Unnamed: 0_level_0", "\u516c\u53f8 \u4ee3\u865f"),
                ("Unnamed: 1_level_0", "\u516c\u53f8\u540d\u7a31"),
                ("\u71df\u696d\u6536\u5165", "\u7576\u6708\u71df\u6536"),
                ("\u71df\u696d\u6536\u5165", "\u4e0a\u6708\u71df\u6536"),
                ("\u71df\u696d\u6536\u5165", "\u53bb\u5e74\u7576\u6708\u71df\u6536"),
                ("\u71df\u696d\u6536\u5165", "\u4e0a\u6708\u6bd4\u8f03 \u589e\u6e1b(%)"),
                ("\u71df\u696d\u6536\u5165", "\u53bb\u5e74\u540c\u6708 \u589e\u6e1b(%)"),
                ("\u7d2f\u8a08\u71df\u696d\u6536\u5165", "\u7576\u6708\u7d2f\u8a08\u71df\u6536"),
                ("\u7d2f\u8a08\u71df\u696d\u6536\u5165", "\u53bb\u5e74\u7d2f\u8a08\u71df\u6536"),
                ("\u7d2f\u8a08\u71df\u696d\u6536\u5165", "\u524d\u671f\u6bd4\u8f03 \u589e\u6e1b(%)"),
                ("\u5099\u8a3b", "\u5099\u8a3b"),
            ]
        )
        raw = pd.DataFrame(
            [["2330", "TSMC", "300000", "290000", "200000", "3.44", "50.0", "1500000", "1000000", "50.0", "-"]],
            columns=columns,
        )

        parsed = mops_revenue._parse_mops_revenue_tables([raw])

        self.assertEqual(parsed.loc[0, "stock_id"], "2330")
        self.assertEqual(parsed.loc[0, "company_name"], "TSMC")
        self.assertEqual(parsed.loc[0, "revenue"], "300000")
        self.assertEqual(parsed.loc[0, "revenue_last_year"], "200000")
        self.assertEqual(parsed.loc[0, "yoy_change"], "50.0")

    def test_fetch_mops_month_revenue_keeps_successful_sources(self):
        class FakeFetcher:
            def get_market_revenue(self, year, month, market, company_type):
                if company_type == 0:
                    raise RuntimeError("unexpected fallback")
                return [
                    {
                        "stock_id": "6488",
                        "company_name": "GlobalWafers",
                        "year": year,
                        "month": month,
                        "revenue": "400000",
                        "revenue_last_year": "200000",
                        "yoy_change": "100.0",
                    }
                ]

        def fake_direct(fetcher, year, month, market, company_type):
            if company_type == 1:
                raise RuntimeError("direct failed")
            return [
                {
                    "stock_id": "2330",
                    "company_name": "TSMC",
                    "year": year,
                    "month": month,
                    "revenue": "300000",
                    "revenue_last_year": "200000",
                    "yoy_change": "50.0",
                }
            ]

        with patch("data_layer.mops_revenue.RevenueFetcher", return_value=FakeFetcher()):
            with patch(
                "data_layer.mops_revenue._fetch_market_revenue_with_redirects",
                side_effect=fake_direct,
            ):
                df = mops_revenue.fetch_mops_month_revenue_frame(
                    115,
                    5,
                    markets=("sii",),
                    company_types=(0, 1),
                )

        self.assertEqual(df["stock_id"].tolist(), ["2330", "6488"])
        self.assertEqual(df.loc[0, "mops_company_type"], 0)
        self.assertEqual(df.loc[1, "mops_company_type"], 1)

    def test_fetch_mops_recent_revenue_skips_empty_latest_months(self):
        def fake_month_frame(year, month):
            ym = f"{year}{month:02d}"
            if ym in {"11505", "11504", "11503"}:
                return pd.DataFrame(columns=mops_revenue.MOPS_REVENUE_COLUMNS)
            return pd.DataFrame(
                {
                    "stock_id": ["2330"],
                    "rev_ym": [ym],
                    "rev_yoy": [20.0],
                    "rev_cur": [300000],
                    "rev_ly": [250000],
                }
            )

        with patch("data_layer.mops_revenue.fetch_mops_month_revenue_frame", side_effect=fake_month_frame):
            df = mops_revenue.fetch_mops_recent_revenue_frame("11505", months=2)

        self.assertEqual(df["rev_ym"].tolist(), ["11502", "11501"])

    def test_fetch_mops_month_revenue_exposes_source_errors(self):
        class FakeFetcher:
            def get_market_revenue(self, year, month, market, company_type):
                raise RuntimeError("primary failed")

        with patch("data_layer.mops_revenue.RevenueFetcher", return_value=FakeFetcher()):
            with patch(
                "data_layer.mops_revenue._fetch_market_revenue_with_redirects",
                side_effect=RuntimeError("fallback failed"),
            ):
                df = mops_revenue.fetch_mops_month_revenue_frame(
                    115,
                    5,
                    markets=("sii",),
                    company_types=(0,),
                )

        self.assertTrue(df.empty)
        self.assertIn("primary failed", "\n".join(df.attrs.get("mops_errors", [])))
        self.assertIn("fallback failed", "\n".join(df.attrs.get("mops_errors", [])))

    def test_build_price_snapshot_normalizes_twse_and_tpex(self):
        raw_twse = [
            {
                "Code": "2330",
                "Name": "台積電",
                "ClosingPrice": "856.98",
                "TradeVolume": "30,000",
            }
        ]
        raw_tpex = [
            {
                "SecuritiesCompanyCode": "6488",
                "CompanyName": "環球晶",
                "Close": "450.5",
                "TradingShares": "12,000",
            }
        ]

        df = build_price_snapshot(raw_twse, raw_tpex)

        self.assertEqual(list(df.columns), list(PRICE_SNAPSHOT_CONTRACT.required))
        self.assertEqual(df["stock_id"].tolist(), ["2330", "6488"])
        self.assertEqual(df["market"].tolist(), ["TWSE", "TPEX"])
        self.assertEqual(df["vol_lot"].tolist(), [30.0, 12.0])

    def test_build_price_snapshot_empty_keeps_contract_columns(self):
        df = build_price_snapshot([], [])

        self.assertTrue(df.empty)
        self.assertEqual(list(df.columns), list(PRICE_SNAPSHOT_CONTRACT.required))

    def test_parse_twse_mi_index_price_rows_matches_price_snapshot_input(self):
        payload = {
            "date": "20260602",
            "stat": "OK",
            "tables": [
                {
                    "fields": [
                        "\u8b49\u5238\u4ee3\u865f",
                        "\u8b49\u5238\u540d\u7a31",
                        "\u6210\u4ea4\u80a1\u6578",
                        "\u6536\u76e4\u50f9",
                        "\u6f32\u8dcc(+/-)",
                        "\u6f32\u8dcc\u50f9\u5dee",
                    ],
                    "data": [
                        ["2330", "TSMC", "30,000", "2,380.00", "<p style='color:red'>+</p>", "25.00"],
                    ],
                }
            ],
        }

        rows = parse_twse_mi_index_price_rows(payload)

        self.assertEqual(rows[0]["Code"], "2330")
        self.assertEqual(rows[0]["ClosingPrice"], "2,380.00")
        self.assertEqual(rows[0]["TradeVolume"], "30,000")
        self.assertEqual(rows[0]["Change"], 25.0)
        self.assertEqual(rows[0]["Date"], "20260602")

    def test_build_revenue_snapshot_and_recent_metrics(self):
        raw_twse = [
            {
                "公司代號": "2330",
                "資料年月": "115/04",
                "營業收入-當月營收": "300,000",
                "營業收入-去年當月營收": "200,000",
                "營業收入-去年同月增減(%)": "50.0",
            },
            {
                "公司代號": "2330",
                "資料年月": "115/03",
                "營業收入-當月營收": "240,000",
                "營業收入-去年當月營收": "200,000",
                "營業收入-去年同月增減(%)": "20.0",
            },
        ]

        df_rev = build_revenue_snapshot(raw_twse, [])
        latest = build_latest_revenue_view(df_rev)
        recent = build_recent_revenue_metrics(df_rev, months=2)

        self.assertEqual(df_rev["rev_ym"].tolist(), ["11504", "11503"])
        self.assertEqual(latest.loc[0, "rev_ym"], "11504")
        self.assertEqual(recent.loc[0, "avg_rev_yoy"], 35.0)
        self.assertEqual(recent.loc[0, "latest_rev_yoy"], 50.0)
        self.assertEqual(recent.loc[0, "prev_rev_yoy"], 20.0)

    def test_build_public_pe_snapshot_supports_tpex_fallback_columns(self):
        raw_tpex = [
            {
                "股票代號": "6488",
                "本益比": "18.5",
            }
        ]

        df = build_public_pe_snapshot([], raw_tpex)

        self.assertEqual(list(df.columns), list(PUBLIC_PE_CONTRACT.required))
        self.assertEqual(df.loc[0, "stock_id"], "6488")
        self.assertEqual(df.loc[0, "pe_ratio_public"], 18.5)

    def test_attach_public_valuation_adds_official_pe_and_ttm_eps(self):
        df_price = pd.DataFrame(
            {
                "stock_id": ["2330"],
                "close": [900.0],
            }
        )
        df_pe = pd.DataFrame(
            {
                "stock_id": ["2330"],
                "pe_ratio_public": [30.0],
            }
        )

        result = attach_public_valuation(df_price, df_pe)

        self.assertEqual(result.loc[0, "pe_ratio"], 30.0)
        self.assertEqual(result.loc[0, "ttm_eps"], 30.0)
        self.assertTrue(pd.notna(result.loc[0, "pe_label"]))

    def test_build_institutional_net_buy_frame_combines_primary_and_secondary(self):
        df = build_institutional_net_buy_frame(
            stock_ids=["2330", "2317"],
            primary_net_shares=["1,000", "-500"],
            secondary_net_shares=["250", "100"],
        )

        self.assertEqual(df["stock_id"].tolist(), ["2330", "2317"])
        self.assertEqual(df["foreign_net_shares"].tolist(), [1250, -400])

    def test_missing_required_columns_reports_contract_gap(self):
        df = pd.DataFrame({"stock_id": ["2330"]})

        missing = missing_required_columns(df, PRICE_SNAPSHOT_CONTRACT)

        self.assertEqual(missing, ["stock_name", "market", "close", "vol_lot"])


if __name__ == "__main__":
    unittest.main()


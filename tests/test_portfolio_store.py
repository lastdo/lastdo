import tempfile
import unittest
from pathlib import Path

from data_layer.contracts import PORTFOLIO_ITEM_FIELDS
from data_layer import portfolio_store


class PortfolioStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_file = portfolio_store.PORTFOLIO_FILE
        portfolio_store.PORTFOLIO_FILE = Path(self.temp_dir.name) / "portfolio.json"

    def tearDown(self):
        portfolio_store.PORTFOLIO_FILE = self.original_file
        self.temp_dir.cleanup()

    def test_normalize_portfolio_item_has_stable_contract_and_aliases(self):
        item = portfolio_store.normalize_portfolio_item(
            {
                "symbol": "2330",
                "name": "台積電",
                "price": "900.5",
                "shares": "1000",
            },
            family_id="home",
        )

        self.assertEqual(tuple(item.keys()), PORTFOLIO_ITEM_FIELDS)
        self.assertEqual(item["stock_id"], "2330")
        self.assertEqual(item["symbol"], "2330")
        self.assertEqual(item["stock_name"], "台積電")
        self.assertEqual(item["name"], "台積電")
        self.assertEqual(item["avg_cost"], 900.5)
        self.assertEqual(item["price"], 900.5)
        self.assertEqual(item["shares"], 1000)
        self.assertEqual(item["family_id"], "home")

    def test_local_create_update_delete_portfolio_item(self):
        created = portfolio_store.create_portfolio_item(
            family_id="home",
            stock_id="2330",
            avg_cost=800.0,
            shares=100,
            stock_name="台積電",
        )

        loaded = portfolio_store.load_portfolio("home")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["row_id"], created["row_id"])
        self.assertEqual(loaded[0]["avg_cost"], 800.0)
        self.assertEqual(loaded[0]["shares"], 100)

        portfolio_store.update_portfolio_item(
            row_id=created["row_id"],
            family_id="home",
            avg_cost=810.5,
            shares=200,
        )
        updated = portfolio_store.load_portfolio("home")
        self.assertEqual(updated[0]["row_id"], created["row_id"])
        self.assertEqual(updated[0]["avg_cost"], 810.5)
        self.assertEqual(updated[0]["price"], 810.5)
        self.assertEqual(updated[0]["shares"], 200)

        portfolio_store.delete_portfolio_item(row_id=created["row_id"], family_id="home")
        self.assertEqual(portfolio_store.load_portfolio("home"), [])

    def test_load_portfolio_filters_by_family_id(self):
        portfolio_store.create_portfolio_item(
            family_id="home",
            stock_id="2330",
            avg_cost=800.0,
            shares=100,
        )
        portfolio_store.create_portfolio_item(
            family_id="office",
            stock_id="2317",
            avg_cost=150.0,
            shares=200,
        )

        home_items = portfolio_store.load_portfolio("home")
        office_items = portfolio_store.load_portfolio("office")

        self.assertEqual([item["stock_id"] for item in home_items], ["2330"])
        self.assertEqual([item["stock_id"] for item in office_items], ["2317"])

    def test_sheet_read_errors_are_wrapped_for_ui(self):
        class BrokenWorksheet:
            def get_all_records(self, expected_headers):
                raise RuntimeError("raw google api failure")

        original_get_worksheet = portfolio_store._get_worksheet
        portfolio_store._get_worksheet = lambda: BrokenWorksheet()
        try:
            with self.assertRaises(portfolio_store.PortfolioStoreConnectionError) as raised:
                portfolio_store._sheet_records()
        finally:
            portfolio_store._get_worksheet = original_get_worksheet

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)


if __name__ == "__main__":
    unittest.main()


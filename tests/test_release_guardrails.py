import py_compile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseGuardrailTests(unittest.TestCase):
    def test_core_streamlit_pages_compile(self):
        paths = [
            ROOT / "Inventory.py",
            ROOT / "pages" / "1_app_tw.py",
            ROOT / "pages" / "2_analysis_history.py",
            ROOT / "pages" / "3_growth_screener.py",
            ROOT / "pages" / "4_chip_screener.py",
            ROOT / "pages" / "5_bottom_screener.py",
            ROOT / "pages" / "6_strategy_backtest.py",
            ROOT / "render_layer" / "style.py",
            ROOT / "render_layer" / "watchlist.py",
            ROOT / "render_layer" / "diagnostics.py",
            ROOT / "backtest_common" / "__init__.py",
            ROOT / "backtest_common" / "double_dragon_rules.py",
            ROOT / "backtest_data_layer" / "__init__.py",
            ROOT / "backtest_data_layer" / "double_dragon_snapshot.py",
            ROOT / "backtest_data_layer" / "finmind_sources.py",
            ROOT / "backtest_data_layer" / "historical_prices.py",
            ROOT / "backtest_render_layer" / "__init__.py",
            ROOT / "backtest_render_layer" / "double_dragon_tables.py",
        ]

        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                py_compile.compile(str(path), doraise=True)

    def test_streamlit_config_does_not_expose_full_error_details(self):
        config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

        self.assertEqual(config["client"]["showErrorDetails"], "type")

    def test_mobile_contrast_css_guardrails_are_present(self):
        style = (ROOT / "render_layer" / "style.py").read_text(encoding="utf-8")

        self.assertIn('div[data-testid="stMetric"] *', style)
        self.assertIn('section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] *', style)
        self.assertIn("color: var(--text-on-dark) !important", style)

    def test_ai_report_keeps_expected_sections(self):
        page = (ROOT / "pages" / "1_app_tw.py").read_text(encoding="utf-8")

        expected_sections = [
            "### 0. 決策摘要",
            "### 1. 趨勢分析",
            "### 2. 基本面分析",
            "### 3. 籌碼面分析",
            "### 4. 基期風險評估",
            "### 5. 技術分析",
        ]
        for section in expected_sections:
            with self.subTest(section=section):
                self.assertIn(section, page)

        self.assertNotIn("### 5. 追蹤條件", page)
        self.assertNotIn("### 6. 資料來源與時間戳", page)

    def test_release_checklist_covers_required_validation(self):
        checklist = (ROOT / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")

        required_items = [
            "python -m py_compile",
            "python -m pytest",
            "手機版",
            "資料來源",
            "AI 分析報告",
            "FinMind",
        ]
        for item in required_items:
            with self.subTest(item=item):
                self.assertIn(item, checklist)

    def test_ci_workflow_runs_release_checks(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python -m py_compile", workflow)
        self.assertIn("python -m pytest", workflow)
        self.assertIn("requirements.txt", workflow)


if __name__ == "__main__":
    unittest.main()

import logging
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


class _IgnoreBareMode(logging.Filter):
    def filter(self, record):
        return "missing ScriptRunContext" not in record.getMessage()


def configure_runtime() -> None:
    logging.getLogger(
        "streamlit.runtime.scriptrunner_utils.script_run_context"
    ).addFilter(_IgnoreBareMode())

    root = str(ROOT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)


def get_portfolio_file() -> Path:
    return ROOT_DIR / "portfolio.json"


def ensure_analysis_dir() -> Path:
    path = ROOT_DIR / "analysis"
    path.mkdir(exist_ok=True)
    return path

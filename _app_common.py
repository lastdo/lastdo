import logging
import os
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


def get_runtime_secret(key: str, default: str = "") -> str:
    """Read secret from Streamlit Cloud first, then fallback to environment."""
    try:
        import streamlit as st

        value = st.secrets.get(key)
        if value not in (None, ""):
            return str(value)
    except Exception:
        pass
    return str(os.getenv(key, default))

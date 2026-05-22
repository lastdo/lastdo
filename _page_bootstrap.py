from pathlib import Path
import sys

from _app_common import configure_runtime


configure_runtime()

ROOT_DIR = Path(__file__).resolve().parent
root = str(ROOT_DIR)
if root not in sys.path:
    sys.path.insert(0, root)

"""Put the repo root and tests dir on sys.path so tests import the package directly.

Deliberately no packaging ceremony: this is a runnable project, not a distributable
library, and a pyproject/editable-install step would be friction for no benefit.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

"""
Ensure the project root is present in `sys.path` for pytest and `core.*` / `agents.*` imports.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

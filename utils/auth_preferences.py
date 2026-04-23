"""
Persists the last auth channel choice (API / Claude CLI / Codex CLI) between runs.
Tokens stay in official directories (~/.claude, ~/.codex); this only avoids re-asking the menu
and aligns the default with what was last used.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Optional


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME", "").strip()
    if base:
        p = Path(base) / "hadouking"
    else:
        p = Path.home() / ".local" / "state" / "hadouking"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path() -> Path:
    return _state_dir() / "last_auth_method.json"


def save_last_auth_method(method: Enum) -> None:
    try:
        name = getattr(method, "name", str(method))
        _path().write_text(json.dumps({"method": name}), encoding="utf-8")
    except OSError:
        pass


def load_last_auth_method_name() -> Optional[str]:
    try:
        raw = _path().read_text(encoding="utf-8")
        data = json.loads(raw)
        m = data.get("method")
        return m if isinstance(m, str) else None
    except (OSError, json.JSONDecodeError, TypeError):
        return None

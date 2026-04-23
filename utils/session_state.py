"""
Persistent CLI session state for Hadouking.

Stores lightweight runtime metadata only:
- selected executor/peer models
- baseline setup answers
- current shared project directory
- last orchestrated session metadata
- last /multi_agent quiz config (for reuse offer)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


_ROOT = Path(__file__).resolve().parent.parent
_PATH = _ROOT / ".hadouking_session.json"


def default_session_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "cli": {
            "selected_model": "",
            "advisor_model": "",
            "peer_follows_executor": True,
        },
        "baseline": {
            "configured": False,
            "model": "",
            "runtime_os": None,
            "runtime_distro": None,
            "auto_approve": False,
            "allow_installs": False,
            "allow_deletes": False,
        },
        "workspace": {
            "shared_project_dir": "",
        },
        "last_orchestrated_session": {},
        "quiz_config": {},
    }


def load_session_state() -> Dict[str, Any]:
    try:
        raw = _PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return default_session_state()
        base = default_session_state()
        for key, value in data.items():
            if isinstance(base.get(key), dict) and isinstance(value, dict):
                base[key].update(value)
            else:
                base[key] = value
        return base
    except (OSError, json.JSONDecodeError, TypeError):
        return default_session_state()


def save_session_state(state: Dict[str, Any]) -> None:
    try:
        payload = load_session_state()
        for key, value in state.items():
            if isinstance(payload.get(key), dict) and isinstance(value, dict):
                payload[key].update(value)
            else:
                payload[key] = value
        _PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def clear_session_state() -> None:
    try:
        _PATH.unlink(missing_ok=True)
    except OSError:
        pass


def session_state_path() -> Path:
    return _PATH

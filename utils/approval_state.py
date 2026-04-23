"""Persistent approval state — scoped per project directory to prevent leakage."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional, Set


class ApprovalState:
    """Manages session and persistent approval state, scoped per project directory."""

    def __init__(self, project_dir: Optional[str] = None):
        self._session_approved_tiers: Set[str] = set()
        self._session_approved_commands: Set[str] = set()
        self._session_always: bool = False
        self._session_id: str = ""

        self._persist_path: Optional[Path] = None
        if project_dir:
            self._persist_path = self._state_path_for_project(project_dir)
        self._persistent_tiers: Set[str] = set()
        self._persistent_commands: Set[str] = set()
        self._load_persistent()

    @staticmethod
    def _state_path_for_project(project_dir: str) -> Path:
        """
        Store approvals in user state directory keyed by project path.
        This avoids trusting mutable files inside the project workspace/repository.
        """
        xdg_state_home = (os.environ.get("XDG_STATE_HOME") or "").strip()
        base = Path(xdg_state_home).expanduser() if xdg_state_home else Path("~/.local/state").expanduser()
        root = base / "hadouking" / "approvals"
        root.mkdir(parents=True, exist_ok=True)
        project_key = hashlib.sha256(str(Path(project_dir).resolve()).encode("utf-8")).hexdigest()[:16]
        return root / f"{project_key}.json"

    def _load_persistent(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            self._persistent_tiers = set(data.get("approved_tiers", []))
            self._persistent_commands = set(data.get("approved_commands", []))
        except Exception:
            pass

    def _save_persistent(self) -> None:
        if not self._persist_path:
            return
        try:
            data = {
                "approved_tiers": sorted(self._persistent_tiers),
                "approved_commands": sorted(self._persistent_commands),
            }
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id

    def check_approved(self, approval_key: str, tier_name: str = "") -> bool:
        if self._session_always:
            return True
        if approval_key in self._session_approved_commands:
            return True
        if approval_key in self._persistent_commands:
            return True
        if tier_name:
            tier_key = f"tier::{tier_name}"
            if tier_key in self._session_approved_tiers:
                return True
            if tier_key in self._persistent_tiers:
                return True
        return False

    def record_approval(
        self,
        decision: str,
        approval_key: str = "",
        tier_name: str = "",
        persist: bool = False,
    ) -> None:
        if decision == "always":
            self._session_always = True
        elif decision == "scope" and tier_name:
            tier_key = f"tier::{tier_name}"
            self._session_approved_tiers.add(tier_key)
            if persist:
                self._persistent_tiers.add(tier_key)
                self._save_persistent()
        elif decision == "command" and approval_key:
            self._session_approved_commands.add(approval_key)
            if persist:
                self._persistent_commands.add(approval_key)
                self._save_persistent()

    def get_summary(self) -> Dict:
        return {
            "session_id": self._session_id,
            "session_tiers": sorted(self._session_approved_tiers),
            "session_commands": len(self._session_approved_commands),
            "session_always": self._session_always,
            "persistent_tiers": sorted(self._persistent_tiers),
            "persistent_commands": len(self._persistent_commands),
        }

    def reset_session(self) -> None:
        self._session_approved_tiers.clear()
        self._session_approved_commands.clear()
        self._session_always = False
        self._session_id = ""

    def clear_persistent(self) -> None:
        self._persistent_tiers.clear()
        self._persistent_commands.clear()
        self._save_persistent()

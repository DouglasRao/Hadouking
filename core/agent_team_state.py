from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


HOOK_ENV_BY_EVENT = {
    "TaskCreated": "HADOUKING_HOOK_TASK_CREATED",
    "TaskCompleted": "HADOUKING_HOOK_TASK_COMPLETED",
    "TeammateIdle": "HADOUKING_HOOK_TEAMMATE_IDLE",
}


class TeamStateError(RuntimeError):
    """Raised when persisted team state is missing or invalid."""


@dataclass
class TeamTask:
    task_id: str
    title: str
    role_key: str
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"
    claimed_by: str = ""
    summary: str = ""
    error: str = ""


class SharedTeamState:
    def __init__(
        self,
        session_dir: Path,
        team_name: str,
        lead_name: str,
        members: List[Tuple[str, str]],
        teammate_mode: str,
        require_plan_approval: bool,
        require_existing_state: bool = False,
    ):
        self.session_dir = session_dir
        self.team_dir = session_dir / "team"
        self.team_dir.mkdir(parents=True, exist_ok=True)

        self.team_name = team_name
        self.lead_name = lead_name
        self.members = members
        self.teammate_mode = teammate_mode
        self.require_plan_approval = require_plan_approval

        self.tasks: Dict[str, TeamTask] = {}
        self.mailbox: List[Dict[str, str]] = []
        self._lock = asyncio.Lock()
        self._mailbox_cursor: Dict[str, int] = {}
        self._idle_signatures: Dict[str, str] = {}

        self.config_path = self.team_dir / "config.json"
        self.tasks_path = self.team_dir / "tasks.json"
        self.mailbox_path = self.team_dir / "mailbox.jsonl"
        self.hooks_path = self.team_dir / "hooks.jsonl"
        self.locks_dir = self.team_dir / "locks"
        self.locks_dir.mkdir(parents=True, exist_ok=True)

        self.persist_config()
        self._load_tasks_from_disk(strict=require_existing_state)
        self._load_mailbox_from_disk(strict=require_existing_state)
        if not require_existing_state:
            self.persist_tasks()

    def persist_config(self) -> None:
        payload = {
            "team_name": self.team_name,
            "lead": self.lead_name,
            "teammate_mode": self.teammate_mode,
            "require_plan_approval": self.require_plan_approval,
            "members": [{"role_key": k, "display_name": v} for k, v in self.members],
            "updated_at": time.time(),
        }
        self.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def persist_tasks(self) -> None:
        payload = {
            "updated_at": time.time(),
            "tasks": [self._serialize_task(t) for t in self.tasks.values()],
        }
        self.tasks_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    async def add_task(self, task: TeamTask) -> None:
        async with self._lock:
            self.tasks[task.task_id] = task
            self.persist_tasks()
            self._emit_event(
                "TaskCreated",
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "role_key": task.role_key,
                    "dependencies": list(task.dependencies),
                },
            )

    async def send_message(self, sender: str, recipient: str, message: str) -> None:
        item = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sender": sender,
            "recipient": recipient,
            "message": message,
        }
        async with self._lock:
            self.mailbox.append(item)
            with self.mailbox_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    async def pull_inbox(self, recipient: str) -> List[Dict[str, str]]:
        async with self._lock:
            cursor = self._mailbox_cursor.get(recipient, 0)
            items = [m for m in self.mailbox[cursor:] if m["recipient"] in (recipient, "*")]
            self._mailbox_cursor[recipient] = len(self.mailbox)
            return items

    async def claim_next_for_role(self, role_key: str, claimant: str) -> Optional[TeamTask]:
        async with self._lock:
            self._load_tasks_from_disk()
            open_exists = False

            for task in self.tasks.values():
                if task.role_key != role_key:
                    continue
                if task.status not in ("pending", "in_progress"):
                    continue
                open_exists = True

                if task.status != "pending":
                    continue
                if not self._deps_completed(task):
                    continue

                if not self._try_create_task_lock(task.task_id, claimant):
                    continue

                task.status = "in_progress"
                task.claimed_by = claimant
                self.persist_tasks()
                self._idle_signatures.pop(claimant, None)
                return task

            reason = "blocked_by_dependencies" if open_exists else "no_remaining_tasks"
            self._emit_teammate_idle(role_key=role_key, claimant=claimant, reason=reason)
            return None

    def _deps_completed(self, task: TeamTask) -> bool:
        for dep_id in task.dependencies:
            dep = self.tasks.get(dep_id)
            if not dep or dep.status != "completed":
                return False
        return True

    async def complete_task(self, task_id: str, summary: str) -> None:
        async with self._lock:
            self._load_tasks_from_disk()
            task = self.tasks[task_id]
            task.status = "completed"
            task.summary = summary[:12000]
            self.persist_tasks()
            self._emit_event(
                "TaskCompleted",
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "role_key": task.role_key,
                    "claimed_by": task.claimed_by,
                    "summary": task.summary,
                },
            )

    async def fail_task(self, task_id: str, error: str) -> None:
        async with self._lock:
            self._load_tasks_from_disk()
            task = self.tasks[task_id]
            task.status = "failed"
            task.error = error[:1200]
            self.persist_tasks()

    async def has_pending_or_in_progress(self) -> bool:
        async with self._lock:
            self._load_tasks_from_disk()
            for task in self.tasks.values():
                if task.status in ("pending", "in_progress"):
                    return True
        return False

    async def has_open_for_role(self, role_key: str) -> bool:
        async with self._lock:
            self._load_tasks_from_disk()
            for task in self.tasks.values():
                if task.role_key == role_key and task.status in ("pending", "in_progress"):
                    return True
        return False

    def counts(self) -> Dict[str, int]:
        out = {"pending": 0, "in_progress": 0, "completed": 0, "failed": 0}
        for task in self.tasks.values():
            if task.status not in out:
                out[task.status] = 0
            out[task.status] += 1
        return out

    async def cleanup(self) -> None:
        async with self._lock:
            self._load_tasks_from_disk()
            active = [t.task_id for t in self.tasks.values() if t.status == "in_progress"]
            if active:
                raise RuntimeError(f"Cannot cleanup team: active tasks still running: {active}")
            marker = {"cleaned_at": time.time(), "status": "cleaned"}
            (self.team_dir / "cleanup.json").write_text(
                json.dumps(marker, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    async def reset_in_progress_tasks(self) -> List[str]:
        async with self._lock:
            self._load_tasks_from_disk()
            reset_ids: List[str] = []
            for task in self.tasks.values():
                if task.status == "in_progress":
                    task.status = "pending"
                    task.claimed_by = ""
                    reset_ids.append(task.task_id)
            if reset_ids:
                self._clear_task_locks(reset_ids)
                self.persist_tasks()
            return reset_ids

    async def prepare_for_resume(self) -> List[str]:
        async with self._lock:
            self._load_tasks_from_disk(strict=True)
            self._load_mailbox_from_disk(strict=True)
            reset_ids: List[str] = []
            open_ids: List[str] = []
            for task in self.tasks.values():
                if task.status in ("pending", "in_progress"):
                    open_ids.append(task.task_id)
                if task.status == "in_progress":
                    task.status = "pending"
                    task.claimed_by = ""
                    reset_ids.append(task.task_id)

            if open_ids:
                self._clear_task_locks(open_ids)
            if reset_ids:
                self.persist_tasks()
            return reset_ids

    def _load_tasks_from_disk(self, *, strict: bool = False) -> None:
        if not self.tasks_path.exists():
            if strict:
                raise TeamStateError(f"Missing team tasks state file: {self.tasks_path}")
            return
        try:
            raw_text = self.tasks_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except Exception as e:
            if strict:
                raise TeamStateError(f"Corrupt team tasks state file: {self.tasks_path} ({e})") from e
            return
        if not isinstance(data, dict):
            if strict:
                raise TeamStateError(f"Invalid team tasks payload in: {self.tasks_path}")
            return

        raw_tasks = data.get("tasks", [])
        if not isinstance(raw_tasks, list):
            if strict:
                raise TeamStateError(f"Invalid 'tasks' list in team state file: {self.tasks_path}")
            return
        loaded: Dict[str, TeamTask] = {}
        for idx, raw in enumerate(raw_tasks):
            task = self._deserialize_task(raw)
            if task:
                loaded[task.task_id] = task
                continue
            if strict:
                raise TeamStateError(
                    f"Invalid task entry at index {idx} in team state file: {self.tasks_path}"
                )

        self.tasks = loaded

    def _load_mailbox_from_disk(self, *, strict: bool = False) -> None:
        if not self.mailbox_path.exists():
            if strict:
                raise TeamStateError(f"Missing team mailbox state file: {self.mailbox_path}")
            return
        loaded: List[Dict[str, str]] = []
        try:
            lines = self.mailbox_path.read_text(encoding="utf-8").splitlines()
            for idx, line in enumerate(lines, start=1):
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    if strict:
                        raise TeamStateError(
                            f"Invalid mailbox entry at line {idx} in: {self.mailbox_path}"
                        )
                    continue
                for key in ("timestamp", "sender", "recipient", "message"):
                    if key not in payload:
                        if strict:
                            raise TeamStateError(
                                f"Mailbox entry missing '{key}' at line {idx} in: {self.mailbox_path}"
                            )
                        break
                else:
                    loaded.append(
                        {
                            "timestamp": str(payload.get("timestamp", "")),
                            "sender": str(payload.get("sender", "")),
                            "recipient": str(payload.get("recipient", "")),
                            "message": str(payload.get("message", "")),
                        }
                    )
        except TeamStateError:
            raise
        except Exception as e:
            if strict:
                raise TeamStateError(f"Corrupt team mailbox state file: {self.mailbox_path} ({e})") from e
            return
        self.mailbox = loaded

    @staticmethod
    def _serialize_task(task: TeamTask) -> Dict[str, object]:
        return {
            "task_id": task.task_id,
            "title": task.title,
            "role_key": task.role_key,
            "dependencies": task.dependencies,
            "status": task.status,
            "claimed_by": task.claimed_by,
            "summary": task.summary,
            "error": task.error,
        }

    @staticmethod
    def _deserialize_task(raw: object) -> Optional[TeamTask]:
        if not isinstance(raw, dict):
            return None
        task_id = str(raw.get("task_id", "")).strip()
        title = str(raw.get("title", "")).strip()
        role_key = str(raw.get("role_key", "")).strip()
        if not task_id or not title or not role_key:
            return None

        deps = raw.get("dependencies", [])
        dependencies = [str(item) for item in deps] if isinstance(deps, list) else []

        return TeamTask(
            task_id=task_id,
            title=title,
            role_key=role_key,
            dependencies=dependencies,
            status=str(raw.get("status", "pending")),
            claimed_by=str(raw.get("claimed_by", "")),
            summary=str(raw.get("summary", "")),
            error=str(raw.get("error", "")),
        )

    def _try_create_task_lock(self, task_id: str, claimant: str) -> bool:
        lock_path = self.locks_dir / f"{self._sanitize_task_id(task_id)}.lock"
        lock_payload = {
            "task_id": task_id,
            "claimed_by": claimant,
            "created_at": time.time(),
        }

        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(lock_payload, f, ensure_ascii=False)
            return True
        except FileExistsError:
            return False
        except Exception:
            return False

    @staticmethod
    def _sanitize_task_id(task_id: str) -> str:
        sanitized = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in task_id.strip())
        return sanitized or "task"

    def _emit_teammate_idle(self, role_key: str, claimant: str, reason: str) -> None:
        payload = {
            "role_key": role_key,
            "claimant": claimant,
            "reason": reason,
        }
        signature = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if self._idle_signatures.get(claimant) == signature:
            return
        self._idle_signatures[claimant] = signature
        self._emit_event("TeammateIdle", payload)

    def _emit_event(self, event: str, payload: Dict[str, object]) -> None:
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": event,
            "payload": payload,
        }

        try:
            with self.hooks_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        hook_env = HOOK_ENV_BY_EVENT.get(event)
        if not hook_env:
            return

        command = os.environ.get(hook_env, "").strip()
        if not command:
            return

        child_env = os.environ.copy()
        child_env["HADOUKING_HOOK_PAYLOAD"] = json.dumps(payload, ensure_ascii=False)

        try:
            argv = shlex.split(command, posix=True)
            if not argv:
                return
            subprocess.run(
                argv,
                shell=False,
                check=False,
                env=child_env,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

    def _clear_task_locks(self, task_ids: List[str]) -> None:
        for task_id in task_ids:
            lock_path = self.locks_dir / f"{self._sanitize_task_id(task_id)}.lock"
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass


__all__ = ["SharedTeamState", "TeamTask", "TeamStateError"]

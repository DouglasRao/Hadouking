from __future__ import annotations

import os
import select
import sys
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional

from rich.console import Group
from rich.panel import Panel
from rich.table import Table

try:
    import termios
    import tty
except Exception:  # pragma: no cover - non-posix fallback
    termios = None
    tty = None


class LiveInputCapture:
    """
    Lightweight stdin capture for `:instruction` + Enter during Rich Live panels.
    Works on any POSIX TTY (macOS/Linux). No-op on Windows or non-TTY streams.

    Usage:
        cap = LiveInputCapture()
        cap.start()
        try:
            with Live(...) as live:
                while not done:
                    instruction = cap.poll()
                    if instruction:
                        agent.submit_instruction(instruction)
                    ...
        finally:
            cap.stop()
    """

    def __init__(self) -> None:
        self._tty_enabled: bool = False
        self._stdin_fd: Optional[int] = None
        self._stdin_attrs: Optional[list] = None
        self._buf: str = ""
        self._capture_runtime: bool = False
        self._runtime_buffer: str = ""
        self._pending: List[str] = []

    def start(self) -> bool:
        if self._tty_enabled:
            return True
        if termios is None or tty is None:
            return False
        if not sys.stdin.isatty():
            return False
        try:
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._stdin_fd = fd
            self._stdin_attrs = attrs
            self._tty_enabled = True
            return True
        except Exception:
            self._tty_enabled = False
            self._stdin_fd = None
            self._stdin_attrs = None
            return False

    def stop(self) -> None:
        if not self._tty_enabled:
            return
        if self._stdin_fd is None or self._stdin_attrs is None:
            self._tty_enabled = False
            return
        try:
            termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._stdin_attrs)
        except Exception:
            pass
        finally:
            self._tty_enabled = False
            self._stdin_fd = None
            self._stdin_attrs = None
            self._buf = ""
            self._capture_runtime = False
            self._runtime_buffer = ""

    def poll(self) -> Optional[str]:
        """Read pending stdin chars and return a completed instruction or None."""
        if not self._tty_enabled or self._stdin_fd is None:
            return None
        while True:
            try:
                ready, _, _ = select.select([self._stdin_fd], [], [], 0)
            except Exception:
                return None
            if not ready:
                break
            try:
                chunk = os.read(self._stdin_fd, 32).decode("utf-8", errors="ignore")
            except Exception:
                return None
            if not chunk:
                break
            self._buf += chunk
            self._consume_buf()
        if self._pending:
            return self._pending.pop(0)
        return None

    def _consume_buf(self) -> None:
        idx = 0
        while idx < len(self._buf):
            ch = self._buf[idx]
            if self._capture_runtime:
                if ch in ("\n", "\r"):
                    msg = self._runtime_buffer.strip()
                    if msg:
                        self._pending.append(msg)
                    self._runtime_buffer = ""
                    self._capture_runtime = False
                elif ch == "\x1b":
                    self._runtime_buffer = ""
                    self._capture_runtime = False
                elif ch in ("\x7f", "\b"):
                    self._runtime_buffer = self._runtime_buffer[:-1]
                else:
                    self._runtime_buffer += ch
                idx += 1
                continue
            if ch == ":":
                self._capture_runtime = True
                self._runtime_buffer = ""
                idx += 1
                continue
            idx += 1
        self._buf = self._buf[idx:]
        if len(self._buf) > 64:
            self._buf = self._buf[-64:]

    @property
    def capturing(self) -> bool:
        return self._capture_runtime

    @property
    def partial(self) -> str:
        return self._runtime_buffer


class AgentTeamUI:
    _SEQ_SHIFT_DOWN = "\x1b[1;2B"
    _SEQ_SHIFT_UP = "\x1b[1;2A"
    _SEQ_DOWN = "\x1b[B"
    _SEQ_UP = "\x1b[A"

    def __init__(
        self,
        title: str,
        workers: List[object],
        team_state: object,
        metrics_provider: Optional[Callable[[], Dict[str, object]]] = None,
    ):
        self.title = title
        self.workers: Dict[str, object] = {w.key: w for w in workers}
        self._worker_order: List[str] = [w.key for w in workers]
        self.team_state = team_state
        self.metrics_provider = metrics_provider

        self._focus_idx = 0
        self._tty_enabled = False
        self._stdin_fd: Optional[int] = None
        self._stdin_attrs: Optional[list] = None
        self._input_buffer = ""
        self._runtime_queue: List[str] = []
        self._capture_runtime = False
        self._runtime_buffer = ""

    def update_worker(self, key: str, status: str, note: str = "") -> None:
        row = self.workers.get(key)
        if not row:
            return
        row.status = status
        row.note = note
        if row.log_path:
            ts = time.strftime("%H:%M:%S")
            row.log_path.parent.mkdir(parents=True, exist_ok=True)
            with row.log_path.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {status.upper()} - {note}\n")

    def start_input_capture(self) -> bool:
        if self._tty_enabled:
            return True
        if termios is None or tty is None:
            return False
        if not sys.stdin.isatty():
            return False
        try:
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            self._stdin_fd = fd
            self._stdin_attrs = attrs
            self._tty_enabled = True
            return True
        except Exception:
            self._tty_enabled = False
            self._stdin_fd = None
            self._stdin_attrs = None
            return False

    def stop_input_capture(self) -> None:
        if not self._tty_enabled:
            return
        if self._stdin_fd is None or self._stdin_attrs is None:
            self._tty_enabled = False
            return
        try:
            termios.tcsetattr(self._stdin_fd, termios.TCSADRAIN, self._stdin_attrs)
        except Exception:
            pass
        finally:
            self._tty_enabled = False
            self._stdin_fd = None
            self._stdin_attrs = None
            self._input_buffer = ""

    def poll_input(self) -> None:
        if not self._tty_enabled or self._stdin_fd is None:
            return

        while True:
            try:
                ready, _, _ = select.select([self._stdin_fd], [], [], 0)
            except Exception:
                return
            if not ready:
                break

            try:
                chunk = os.read(self._stdin_fd, 32).decode("utf-8", errors="ignore")
            except Exception:
                return
            if not chunk:
                break

            self._input_buffer += chunk
            self._consume_input_buffer()

    def _consume_input_buffer(self) -> None:
        sequences = [
            (self._SEQ_SHIFT_DOWN, self._focus_next),
            (self._SEQ_SHIFT_UP, self._focus_prev),
            (self._SEQ_DOWN, self._focus_next),
            (self._SEQ_UP, self._focus_prev),
        ]
        idx = 0
        while idx < len(self._input_buffer):
            ch = self._input_buffer[idx]

            if self._capture_runtime:
                if ch in ("\n", "\r"):
                    runtime_msg = self._runtime_buffer.strip()
                    if runtime_msg:
                        self._runtime_queue.append(runtime_msg)
                    self._runtime_buffer = ""
                    self._capture_runtime = False
                    idx += 1
                    continue
                if ch == "\x1b":
                    self._runtime_buffer = ""
                    self._capture_runtime = False
                    idx += 1
                    continue
                if ch in ("\x7f", "\b"):
                    self._runtime_buffer = self._runtime_buffer[:-1]
                    idx += 1
                    continue
                self._runtime_buffer += ch
                idx += 1
                continue

            if ch == ":":
                self._capture_runtime = True
                self._runtime_buffer = ""
                idx += 1
                continue

            if ch in ("j", "J"):
                self._focus_next()
                idx += 1
                continue
            if ch in ("k", "K"):
                self._focus_prev()
                idx += 1
                continue

            if ch != "\x1b":
                idx += 1
                continue

            matched = False
            for seq, action in sequences:
                if self._input_buffer.startswith(seq, idx):
                    action()
                    idx += len(seq)
                    matched = True
                    break
            if matched:
                continue

            tail = self._input_buffer[idx:]
            if any(seq.startswith(tail) for seq, _ in sequences):
                break
            idx += 1

        self._input_buffer = self._input_buffer[idx:]
        if len(self._input_buffer) > 64:
            self._input_buffer = self._input_buffer[-64:]

    def pop_runtime_instructions(self) -> List[str]:
        if not self._runtime_queue:
            return []
        out = list(self._runtime_queue)
        self._runtime_queue.clear()
        return out

    def _focus_next(self) -> None:
        if not self._worker_order:
            return
        self._focus_idx = (self._focus_idx + 1) % len(self._worker_order)

    def _focus_prev(self) -> None:
        if not self._worker_order:
            return
        self._focus_idx = (self._focus_idx - 1) % len(self._worker_order)

    def _focused_worker(self) -> Optional[object]:
        if not self._worker_order:
            return None
        key = self._worker_order[self._focus_idx]
        return self.workers.get(key)

    def _workers_table(self) -> Table:
        table = Table(title=self.title)
        table.add_column("Focus", no_wrap=True)
        table.add_column("Teammate")
        table.add_column("Status")
        table.add_column("Model")
        table.add_column("Note")

        focused = self._focused_worker()
        focused_key = getattr(focused, "key", None) if focused else None

        for row in self.workers.values():
            marker = ">" if row.key == focused_key else ""
            table.add_row(marker, row.role, row.status, row.model, row.note or "-")
        return table

    def _tasks_table(self) -> Table:
        counts = self.team_state.counts()
        table = Table(
            title=(
                "Shared Task List "
                f"(pending={counts.get('pending', 0)}, "
                f"in_progress={counts.get('in_progress', 0)}, "
                f"completed={counts.get('completed', 0)}, "
                f"failed={counts.get('failed', 0)})"
            )
        )
        table.add_column("Task ID")
        table.add_column("Role")
        table.add_column("State")
        table.add_column("Dependencies")
        table.add_column("Claimed by")
        table.add_column("Title")

        for task in self.team_state.tasks.values():
            table.add_row(
                task.task_id,
                task.role_key,
                task.status,
                ",".join(task.dependencies) if task.dependencies else "-",
                task.claimed_by or "-",
                task.title,
            )
        return table

    @staticmethod
    def _tail_log_lines(log_path: Optional[Path], limit: int = 8) -> List[str]:
        if not log_path or not log_path.exists():
            return ["(no log file)"]
        try:
            with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                lines = deque(f, maxlen=limit)
            out = [line.rstrip() for line in lines if line.strip()]
            return out or ["(no log lines yet)"]
        except Exception:
            return ["(failed to read log)"]

    def _details_panel(self) -> Panel:
        focused = self._focused_worker()
        if focused is None:
            return Panel("No teammate available.", title="Teammate Details", border_style="cyan")

        log_lines = self._tail_log_lines(getattr(focused, "log_path", None), limit=8)
        detail_text = (
            f"role: {focused.role}\n"
            f"status: {focused.status}\n"
            f"note: {focused.note or '-'}\n"
            f"model: {focused.model}\n\n"
            "log (last lines):\n"
            + "\n".join(log_lines)
            + "\n\n"
            "shortcuts: Shift+Down next | Shift+Up previous | fallback j/k\n"
            "runtime prompt: type `:your instruction` + Enter to queue to lead"
        )
        if self._capture_runtime:
            detail_text += f"\n\ncapturing runtime prompt: :{self._runtime_buffer}"
        return Panel(detail_text, title=f"Teammate Details [{focused.key}]", border_style="cyan")

    def _metrics_panel(self) -> Optional[Panel]:
        if not self.metrics_provider:
            return None
        try:
            metrics = self.metrics_provider() or {}
        except Exception:
            return None

        if not metrics:
            return None

        header = (
            f"executor_ctx={metrics.get('executor_context_window', '-')} | "
            f"peer_ctx={metrics.get('peer_context_window', '-')} | "
            f"contexts_used={metrics.get('total_context_injections', 0)} | "
            f"docs={metrics.get('total_context_docs', 0)}"
        )
        lines = [header, ""]

        per_agent = metrics.get("agents", [])
        if per_agent:
            for item in per_agent:
                lines.append(
                    f"{item['label']}: {item['used']}/{item['max']} ({item['pct']:.1f}%) "
                    f"ctx={item['ctx_injections']}/{item['ctx_docs']} actions={item['actions']}"
                )
        else:
            lines.append("sem agentes ativos")

        return Panel(
            "\n".join(lines),
            title="Context Usage",
            border_style="magenta",
        )

    def render(self):
        parts = [self._workers_table(), self._tasks_table()]
        metrics_panel = self._metrics_panel()
        if metrics_panel is not None:
            parts.append(metrics_panel)
        parts.append(self._details_panel())
        return Group(*parts)

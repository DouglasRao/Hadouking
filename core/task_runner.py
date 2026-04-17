import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from config import Config
from utils.ui import console


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskSession:
    id: int
    name: str
    agent: Any
    state: TaskState = TaskState.PENDING
    asyncio_task: Optional[asyncio.Task] = None
    error: Optional[str] = None


class BackgroundTaskRegistry:
    """Track multiple async tasks with per-agent pause and resume support."""

    def __init__(self):
        self._sessions: Dict[int, TaskSession] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()
        n = Config.HADOUKING_MAX_BG_TASKS
        self._concurrency = asyncio.Semaphore(n) if n > 0 else None

    def list_sessions(self) -> List[TaskSession]:
        return list(self._sessions.values())

    def get(self, task_id: int) -> Optional[TaskSession]:
        return self._sessions.get(task_id)

    async def spawn(
        self,
        name: str,
        agent: Any,
        initial_message: str,
        on_complete: Optional[Callable[[TaskSession], None]] = None,
    ) -> TaskSession:
        async with self._lock:
            tid = self._next_id
            self._next_id += 1
            session = TaskSession(id=tid, name=name, agent=agent)
            self._sessions[tid] = session

        async def _run():
            async def _body():
                session.state = TaskState.RUNNING
                try:
                    await agent.process_message(initial_message)
                    session.state = TaskState.DONE
                except asyncio.CancelledError:
                    session.state = TaskState.CANCELLED
                    agent.active = False
                    raise
                except Exception as e:
                    session.state = TaskState.FAILED
                    session.error = str(e)
                    console.print(f"[red]Task {tid} failed: {e}[/red]")
                finally:
                    if on_complete:
                        on_complete(session)

            if self._concurrency:
                async with self._concurrency:
                    await _body()
            else:
                await _body()

        session.asyncio_task = asyncio.create_task(_run())
        return session

    def pause_task(self, task_id: int) -> str:
        s = self._sessions.get(task_id)
        if not s:
            return f"Task {task_id} not found."
        s.agent.pause()
        if s.state == TaskState.RUNNING:
            s.state = TaskState.PAUSED
        return f"Task {task_id} pause requested (agent '{s.name}')."

    def resume_task(self, task_id: int) -> str:
        s = self._sessions.get(task_id)
        if not s:
            return f"Task {task_id} not found."
        s.agent.resume()
        if s.state == TaskState.PAUSED:
            s.state = TaskState.RUNNING
        return f"Task {task_id} resumed (agent '{s.name}')."

    async def cancel_task(self, task_id: int) -> str:
        s = self._sessions.get(task_id)
        if not s:
            return f"Task {task_id} not found."
        s.agent.active = False
        if s.asyncio_task and not s.asyncio_task.done():
            s.asyncio_task.cancel()
            try:
                await s.asyncio_task
            except asyncio.CancelledError:
                pass
        s.state = TaskState.CANCELLED
        return f"Task {task_id} cancelled."

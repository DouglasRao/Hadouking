import asyncio
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_IMPORT_ERROR = None
try:
    from core.multi_agent_orchestrator import MultiAgentOrchestrator
    from core.multi_agent_orchestrator import WorkerRow
    from core.agent_team_state import SharedTeamState
    from core.agent_team_state import TeamTask
    from core.agent_team_ui import AgentTeamUI
    from utils.ui import console
except ModuleNotFoundError as exc:
    _IMPORT_ERROR = exc
    MultiAgentOrchestrator = None
    SharedTeamState = None
    TeamTask = None
    AgentTeamUI = None
    WorkerRow = None
    console = None


class _ManagerStub:
    def __init__(self, shared_project_dir: str):
        self.shared_project_dir = shared_project_dir


def _normalize_event_name(value: str) -> str:
    return value.lower().replace("_", "").replace("-", "").replace(" ", "")


async def _maybe_await(call_result):
    if inspect.isawaitable(call_result):
        return await call_result
    return call_result


@unittest.skipIf(_IMPORT_ERROR is not None, f"dependencies missing for agent team tests: {_IMPORT_ERROR}")
class TestAgentTeamsState(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.session_dir = Path(self._tmp.name) / "session"
        self.state = SharedTeamState(
            session_dir=self.session_dir,
            team_name="test-team",
            lead_name="lead",
            members=[("recon_passive_agent", "Recon Passive"), ("vuln_scanner_agent", "Vuln Scanner")],
            teammate_mode="in-process",
            require_plan_approval=False,
        )

    async def asyncTearDown(self):
        self._tmp.cleanup()

    async def test_state_persistence_dependencies_and_claim_flow(self):
        t1 = TeamTask(
            task_id="T1",
            role_key="recon_passive_agent",
            title="Passive recon",
        )
        t2 = TeamTask(
            task_id="T2",
            role_key="vuln_scanner_agent",
            title="Scanner run",
            dependencies=["T1"],
        )

        await self.state.add_task(t1)
        await self.state.add_task(t2)

        blocked = await self.state.claim_next_for_role("vuln_scanner_agent", claimant="worker-vuln")
        self.assertIsNone(blocked)

        first = await self.state.claim_next_for_role("recon_passive_agent", claimant="worker-recon")
        self.assertIsNotNone(first)
        self.assertEqual("T1", first.task_id)
        self.assertEqual("worker-recon", first.claimed_by)

        await self.state.complete_task("T1", "done")

        second = await self.state.claim_next_for_role("vuln_scanner_agent", claimant="worker-vuln")
        self.assertIsNotNone(second)
        self.assertEqual("T2", second.task_id)
        self.assertEqual("worker-vuln", second.claimed_by)

        payload = json.loads(self.state.tasks_path.read_text(encoding="utf-8"))
        by_id = {row["task_id"]: row for row in payload["tasks"]}
        self.assertEqual("completed", by_id["T1"]["status"])
        self.assertEqual("in_progress", by_id["T2"]["status"])
        self.assertEqual("worker-vuln", by_id["T2"]["claimed_by"])

    async def test_claim_is_single_winner_and_lock_file_persists(self):
        await self.state.add_task(
            TeamTask(
                task_id="T1",
                role_key="recon_passive_agent",
                title="Race claim",
            )
        )

        async def _claim(worker_name: str):
            return await self.state.claim_next_for_role("recon_passive_agent", claimant=worker_name)

        results = await asyncio.gather(*[_claim(f"w{i}") for i in range(6)])
        winners = [r for r in results if r is not None]

        self.assertEqual(1, len(winners), "only one worker should claim the same pending task")
        self.assertEqual("in_progress", self.state.tasks["T1"].status)

        payload = json.loads(self.state.tasks_path.read_text(encoding="utf-8"))
        claimed_by = next(row["claimed_by"] for row in payload["tasks"] if row["task_id"] == "T1")
        self.assertTrue(claimed_by.startswith("w"))

        lock_files = list((self.state.team_dir / "locks").glob("*.lock"))
        self.assertEqual(1, len(lock_files), f"expected persisted claim lock file, got: {lock_files}")

    async def test_mailbox_cursor_and_broadcast_delivery(self):
        await self.state.send_message("lead", "worker-a", "private message")
        await self.state.send_message("lead", "*", "broadcast message")

        first_pull = await self.state.pull_inbox("worker-a")
        self.assertEqual(2, len(first_pull))
        self.assertEqual("private message", first_pull[0]["message"])
        self.assertEqual("broadcast message", first_pull[1]["message"])

        second_pull = await self.state.pull_inbox("worker-a")
        self.assertEqual([], second_pull)

        worker_b_pull = await self.state.pull_inbox("worker-b")
        self.assertEqual(1, len(worker_b_pull))
        self.assertEqual("broadcast message", worker_b_pull[0]["message"])

        lines = self.state.mailbox_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(2, len(lines))

    async def test_resume_requires_explicit_state_files_and_reports_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "resume-missing"
            with self.assertRaisesRegex(RuntimeError, "Missing team tasks state file"):
                SharedTeamState(
                    session_dir=session_dir,
                    team_name="test-team",
                    lead_name="lead",
                    members=[("recon_passive_agent", "Recon Passive")],
                    teammate_mode="in-process",
                    require_plan_approval=False,
                    require_existing_state=True,
                )

            base = SharedTeamState(
                session_dir=Path(tmp) / "resume-corrupt",
                team_name="test-team",
                lead_name="lead",
                members=[("recon_passive_agent", "Recon Passive")],
                teammate_mode="in-process",
                require_plan_approval=False,
            )
            await base.send_message("lead", "*", "hello")
            base.tasks_path.write_text("{ invalid json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Corrupt team tasks state file"):
                SharedTeamState(
                    session_dir=base.session_dir,
                    team_name="test-team",
                    lead_name="lead",
                    members=[("recon_passive_agent", "Recon Passive")],
                    teammate_mode="in-process",
                    require_plan_approval=False,
                    require_existing_state=True,
                )

    async def test_resume_mailbox_continuity_and_completed_task_not_reprocessed(self):
        await self.state.add_task(
            TeamTask(task_id="T1", role_key="recon_passive_agent", title="First task")
        )
        await self.state.add_task(
            TeamTask(task_id="T2", role_key="recon_passive_agent", title="Second task")
        )
        await self.state.send_message("lead", "recon_passive_agent", "queued instruction")
        await self.state.send_message("lead", "*", "queued broadcast")

        first = await self.state.claim_next_for_role("recon_passive_agent", claimant="worker-a")
        self.assertIsNotNone(first)
        self.assertEqual("T1", first.task_id)
        await self.state.complete_task("T1", "completed once")

        second = await self.state.claim_next_for_role("recon_passive_agent", claimant="worker-a")
        self.assertIsNotNone(second)
        self.assertEqual("T2", second.task_id)
        self.assertEqual("in_progress", self.state.tasks["T2"].status)

        resumed = SharedTeamState(
            session_dir=self.session_dir,
            team_name="test-team",
            lead_name="lead",
            members=[("recon_passive_agent", "Recon Passive")],
            teammate_mode="in-process",
            require_plan_approval=False,
            require_existing_state=True,
        )
        reset_ids = await resumed.prepare_for_resume()
        self.assertEqual(["T2"], reset_ids)

        resumed_messages = await resumed.pull_inbox("recon_passive_agent")
        self.assertEqual(2, len(resumed_messages))
        self.assertEqual("queued instruction", resumed_messages[0]["message"])
        self.assertEqual("queued broadcast", resumed_messages[1]["message"])

        claimed_after_resume = await resumed.claim_next_for_role(
            "recon_passive_agent", claimant="worker-b"
        )
        self.assertIsNotNone(claimed_after_resume)
        self.assertEqual("T2", claimed_after_resume.task_id)
        self.assertEqual("completed", resumed.tasks["T1"].status)

    async def test_hooks_task_lifecycle_and_idle_event_if_api_exists(self):
        emitter_name = None
        for candidate in ("_emit_event", "_emit_hook", "emit_hook", "_dispatch_hook", "_notify_hook"):
            if hasattr(self.state, candidate):
                emitter_name = candidate
                break
        if not emitter_name:
            self.skipTest("Hook emitter API not exposed on SharedTeamState in this build")

        idle_method = None
        for candidate in (
            "mark_teammate_idle",
            "notify_teammate_idle",
            "_emit_teammate_idle",
            "emit_teammate_idle",
            "teammate_idle",
        ):
            if hasattr(self.state, candidate):
                idle_method = getattr(self.state, candidate)
                break
        if idle_method is None:
            self.skipTest("Teammate idle hook API not exposed in this build")

        seen = []
        original_emitter = getattr(self.state, emitter_name)
        if inspect.iscoroutinefunction(original_emitter):
            async def _recorder(*args, **kwargs):
                seen.append((args, kwargs))
        else:
            def _recorder(*args, **kwargs):
                seen.append((args, kwargs))

        with patch.object(self.state, emitter_name, new=_recorder):
            await self.state.add_task(
                TeamTask(
                    task_id="T1",
                    role_key="recon_passive_agent",
                    title="Hook created",
                )
            )
            await self.state.complete_task("T1", "Hook completed")

            for args in (
                ("recon_passive_agent", "worker", "test_reason"),
                ("Recon Passive", "idle"),
                ("Recon Passive",),
                ("recon_passive_agent",),
                (),
            ):
                try:
                    await _maybe_await(idle_method(*args))
                    break
                except TypeError:
                    continue
            else:
                self.fail("Could not call teammate idle method with supported argument shapes")

        expected = {"taskcreated", "taskcompleted", "teammateidle"}
        captured = set()
        for args, kwargs in seen:
            values = list(args) + list(kwargs.values())
            for value in values:
                if isinstance(value, str):
                    norm = _normalize_event_name(value)
                    if norm in expected:
                        captured.add(norm)
                elif isinstance(value, dict):
                    for key in ("event", "name", "type", "hook"):
                        hook_name = value.get(key)
                        if isinstance(hook_name, str):
                            norm = _normalize_event_name(hook_name)
                            if norm in expected:
                                captured.add(norm)

        self.assertIn("taskcreated", captured)
        self.assertIn("taskcompleted", captured)
        self.assertIn("teammateidle", captured)


@unittest.skipIf(_IMPORT_ERROR is not None, f"dependencies missing for agent team tests: {_IMPORT_ERROR}")
class TestAgentTeamsInteractiveFallback(unittest.TestCase):
    def test_open_iterm_views_falls_back_when_not_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = MultiAgentOrchestrator(auth_manager=None, manager=_ManagerStub(tmp))
            worker = WorkerRow(
                key="recon_passive_agent",
                role="Recon Passive",
                model="gpt-4o",
                log_path=Path(tmp) / "recon.log",
            )

            with patch.object(MultiAgentOrchestrator, "_iterm_supported", return_value=False):
                with patch.object(MultiAgentOrchestrator, "_tmux_supported", return_value=False):
                    with patch.object(MultiAgentOrchestrator, "_split_iterm2") as split_mock:
                        with patch.object(console, "print") as print_mock:
                            orchestrator._open_iterm_views([worker], Path(tmp))

            split_mock.assert_not_called()
            printed = " ".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
            self.assertIn("No supported terminal multiplexer detected", printed)

    def test_runtime_instruction_queue_from_colon_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = SharedTeamState(
                session_dir=Path(tmp) / "session",
                team_name="test-team",
                lead_name="lead",
                members=[("recon_passive_agent", "Recon Passive")],
                teammate_mode="in-process",
                require_plan_approval=False,
            )
            worker = WorkerRow(
                key="brain",
                role="Pentest Brain",
                model="gpt-4o",
                log_path=Path(tmp) / "brain.log",
            )
            ui = AgentTeamUI("Test Team", [worker], state)
            ui._input_buffer = ":priorize API first\n"  # simulated captured stdin chunk
            ui._consume_input_buffer()
            queued = ui.pop_runtime_instructions()
            self.assertEqual(["priorize API first"], queued)

    def test_resumable_session_metadata_and_resume_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = MultiAgentOrchestrator(auth_manager=None, manager=_ManagerStub(tmp))
            session_dir = Path(tmp) / "session"
            team_dir = session_dir / "team"
            team_dir.mkdir(parents=True, exist_ok=True)

            manifest = {
                "target": "example.test",
                "mode": "auto",
                "selected_worker_keys": ["recon_passive_agent"],
                "models": {"pentest_brain_agent": "gpt-4o", "recon_passive_agent": "gpt-4o"},
            }
            (session_dir / "session_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (team_dir / "tasks.json").write_text(
                json.dumps(
                    {
                        "updated_at": 1,
                        "tasks": [
                            {
                                "task_id": "T1",
                                "title": "Passive",
                                "role_key": "recon_passive_agent",
                                "dependencies": [],
                                "status": "completed",
                                "claimed_by": "worker",
                                "summary": "done",
                                "error": "",
                            },
                            {
                                "task_id": "T2",
                                "title": "Passive 2",
                                "role_key": "recon_passive_agent",
                                "dependencies": [],
                                "status": "pending",
                                "claimed_by": "",
                                "summary": "",
                                "error": "",
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (team_dir / "mailbox.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-01-01 00:00:00",
                        "sender": "lead",
                        "recipient": "recon_passive_agent",
                        "message": "resume this",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            details = orchestrator.inspect_resumable_session(str(session_dir))
            self.assertTrue(details["resumable"])
            self.assertEqual(1, details["counts"].get("completed"))
            self.assertEqual(1, details["counts"].get("pending"))
            self.assertEqual(["recon_passive_agent"], details["selected_worker_keys"])

            (team_dir / "tasks.json").write_text("{ invalid", encoding="utf-8")
            bad_details = orchestrator.inspect_resumable_session(str(session_dir))
            self.assertFalse(bad_details["resumable"])
            joined_errors = "\n".join(str(e) for e in bad_details["errors"])
            self.assertIn("tasks state file is corrupt", joined_errors)


@unittest.skipIf(_IMPORT_ERROR is not None, f"dependencies missing for agent team tests: {_IMPORT_ERROR}")
class TestAgentTeamResumeFlow(unittest.IsolatedAsyncioTestCase):
    async def test_resume_precheck_blocks_missing_mailbox_and_valid_session_calls_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            orchestrator = MultiAgentOrchestrator(auth_manager=None, manager=_ManagerStub(tmp))
            session_dir = Path(tmp) / "session"
            team_dir = session_dir / "team"
            team_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "session_manifest.json").write_text(
                json.dumps(
                    {
                        "target": "example.test",
                        "mode": "auto",
                        "selected_worker_keys": ["recon_passive_agent"],
                        "models": {"pentest_brain_agent": "gpt-4o"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (team_dir / "tasks.json").write_text(
                json.dumps(
                    {
                        "updated_at": 1,
                        "tasks": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "mailbox state file missing"):
                await orchestrator.resume(str(session_dir), available_mcps={})

            (team_dir / "mailbox.jsonl").write_text("", encoding="utf-8")
            with patch.object(orchestrator, "_execute_session", new=AsyncMock(return_value="ok")) as exec_mock:
                result = await orchestrator.resume(str(session_dir), available_mcps={})

            self.assertEqual("ok", result)
            exec_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

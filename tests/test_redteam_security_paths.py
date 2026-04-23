import asyncio
import json
from types import SimpleNamespace

from config import Config
from core.agent_team_state import SharedTeamState
from core.agent import Agent
from core.browser import BrowserManager
from core.mcp import MCPClient
from utils.approval_state import ApprovalState
from utils.tools import execute_command


def test_execute_command_blocks_shell_metacharacters():
    async def _run():
        return await execute_command("printf alpha && printf beta")

    output = asyncio.run(_run())
    assert "metacharacters are not allowed" in output.lower()


def test_mcp_client_blocks_non_allowlisted_command(monkeypatch):
    seen = {}

    async def fake_exec(cmd, *args, **kwargs):
        seen["cmd"] = cmd
        seen["args"] = args
        seen["kwargs"] = kwargs

        class DummyProc:
            stdin = None
            stdout = None
            stderr = None

        return DummyProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    client = MCPClient("demo", {"command": "custom-binary", "args": ["--flag"]})
    ok = asyncio.run(client.connect())

    assert ok is False
    assert seen == {}


def test_approval_state_ignores_project_local_approvals_file(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    project_dir = tmp_path / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    approvals = project_dir / ".hadouking_approvals.json"
    approvals.write_text(
        json.dumps({"approved_tiers": ["tier::NETWORK"], "approved_commands": []}),
        encoding="utf-8",
    )

    state = ApprovalState(str(project_dir))
    assert state.check_approved("nonexistent", "NETWORK") is False


def test_team_hook_executes_without_shell_true(monkeypatch, tmp_path):
    session_dir = tmp_path / "session"
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return None

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setenv("HADOUKING_HOOK_TASK_CREATED", "echo test-hook")

    team = SharedTeamState(
        session_dir=session_dir,
        team_name="t",
        lead_name="lead",
        members=[("role", "name")],
        teammate_mode="temporary",
        require_plan_approval=False,
    )

    team._emit_event("TaskCreated", {"task_id": "1"})

    assert captured["command"] == ["echo", "test-hook"]
    assert captured["shell"] is False
    assert "HADOUKING_HOOK_PAYLOAD" in captured["env"]


def test_browser_screenshot_path_rejects_traversal():
    assert BrowserManager._safe_screenshot_path("../secrets.png") is None
    assert BrowserManager._safe_screenshot_path("/tmp/a.png") is None
    assert BrowserManager._safe_screenshot_path("artifacts/safe.png") == "artifacts/safe.png"


def test_inline_command_extraction_disabled_by_default(monkeypatch):
    monkeypatch.setattr(Config, "HADOUKING_ALLOW_INLINE_BASH_FALLBACK", False)
    text = "Use this hint: `curl http://127.0.0.1`"
    assert Agent._extract_bash_commands(object(), text) == []


def test_inline_command_extraction_legacy_mode(monkeypatch):
    monkeypatch.setattr(Config, "HADOUKING_ALLOW_INLINE_BASH_FALLBACK", True)
    text = "Use this hint: `curl http://127.0.0.1`"
    assert Agent._extract_bash_commands(object(), text) == ["curl http://127.0.0.1"]


def test_always_confirm_ignores_cached_approval(monkeypatch):
    prompted = {"called": False}

    def fake_ask(*args, **kwargs):
        prompted["called"] = True
        return False

    monkeypatch.setattr("core.agent.ask_command_approval", fake_ask)
    monkeypatch.setattr("core.agent.exec_mode", lambda: "always_confirm")

    dummy_agent = SimpleNamespace(
        _is_auto_approve_active=lambda: False,
        _scoped_approval_key=lambda key: key,
        approval_state=SimpleNamespace(check_approved=lambda approval_key, tier_name="": True),
        get_approval_cache_state=lambda: {},
        _step=lambda *args, **kwargs: None,
    )

    decision = asyncio.run(
        Agent._safety_check(
            dummy_agent,
            "echo test",
            tier_label="NETWORK",
            tier_name="NETWORK",
            approval_key="bash::echo test",
        )
    )

    assert prompted["called"] is True
    assert decision is False

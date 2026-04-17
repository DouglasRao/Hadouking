import asyncio

from core.agent import Agent


def _build_agent(tmp_path, name: str) -> Agent:
    return Agent(
        name=name,
        model="gpt-4o",
        system_prompt="test",
        project_dir=str(tmp_path),
    )


def test_exact_command_approval_cached_in_session(tmp_path, monkeypatch):
    agent = _build_agent(tmp_path, "agent-cache")
    calls = []

    def fake_prompt(command, tier_label="", approval_cache=None):
        calls.append((command, tier_label, approval_cache))
        return "command"

    monkeypatch.setattr("core.agent.ask_command_approval", fake_prompt)
    command = "curl -s https://example.com"
    key = agent._approval_key_for_bash(command)

    async def run():
        assert await agent._safety_check(command, tier_name="NETWORK", approval_key=key) is True
        assert await agent._safety_check(command, tier_name="NETWORK", approval_key=key) is True

    asyncio.run(run())
    assert len(calls) == 1


def test_tier_scope_is_shared_between_bash_and_python(tmp_path, monkeypatch):
    agent = _build_agent(tmp_path, "agent-tier")
    calls = []

    def fake_prompt(command, tier_label="", approval_cache=None):
        calls.append((command, tier_label, approval_cache))
        return "scope"

    monkeypatch.setattr("core.agent.ask_command_approval", fake_prompt)
    bash_cmd = "curl -s https://example.com"
    py_script = "import requests\nprint('ok')"

    async def run():
        assert await agent._safety_check(
            bash_cmd,
            tier_name="NETWORK",
            approval_key=agent._approval_key_for_bash(bash_cmd),
        ) is True
        assert await agent._safety_check(
            "python3 <temp script>",
            tier_name="NETWORK",
            approval_key=agent._approval_key_for_python(py_script),
        ) is True

    asyncio.run(run())
    assert len(calls) == 1


def test_command_approval_does_not_leak_between_agents(tmp_path, monkeypatch):
    agent_a = _build_agent(tmp_path / "a", "agent-a")
    agent_b = _build_agent(tmp_path / "b", "agent-b")
    prompt_calls = {"count": 0}

    def approve_prompt(command, tier_label="", approval_cache=None):
        prompt_calls["count"] += 1
        return "command"

    monkeypatch.setattr("core.agent.ask_command_approval", approve_prompt)
    command = "curl -s https://example.com"
    key_a = agent_a._approval_key_for_bash(command)
    key_b = agent_b._approval_key_for_bash(command)

    async def run_a():
        assert await agent_a._safety_check(command, tier_name="NETWORK", approval_key=key_a) is True
        assert await agent_a._safety_check(command, tier_name="NETWORK", approval_key=key_a) is True

    asyncio.run(run_a())
    assert prompt_calls["count"] == 1

    def deny_prompt(command, tier_label="", approval_cache=None):
        prompt_calls["count"] += 1
        return "deny"

    monkeypatch.setattr("core.agent.ask_command_approval", deny_prompt)

    async def run_b():
        assert await agent_b._safety_check(command, tier_name="NETWORK", approval_key=key_b) is False

    asyncio.run(run_b())
    assert prompt_calls["count"] == 2

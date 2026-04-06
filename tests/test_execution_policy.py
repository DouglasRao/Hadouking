"""Local execution policy (tiered layers)."""

from core.execution_policy import (
    ExecTier,
    classify_command,
    classify_python_script,
    is_blocked,
    needs_user_confirmation,
)


def test_classify_ls_read():
    t, _ = classify_command("ls -la /tmp")
    assert t == ExecTier.READ_LOCAL


def test_classify_curl_network():
    t, _ = classify_command("curl -s http://example.com")
    assert t == ExecTier.NETWORK


def test_classify_sudo_privileged():
    t, _ = classify_command("sudo nmap -sV 127.0.0.1")
    assert t == ExecTier.PRIVILEGED


def test_classify_compound_max_tier():
    t, _ = classify_command("ls -la && curl http://x")
    assert t == ExecTier.NETWORK


def test_python_subprocess_privileged():
    t, _ = classify_python_script("import subprocess\nsubprocess.run(['id'])")
    assert t == ExecTier.PRIVILEGED


def test_needs_confirm_tiered():
    assert needs_user_confirmation(ExecTier.READ_LOCAL, auto_approve=False) is False
    assert needs_user_confirmation(ExecTier.NETWORK, auto_approve=False) is True
    assert needs_user_confirmation(ExecTier.NETWORK, auto_approve=True) is False


def test_always_confirm_mode(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "PENTESTLLM_EXEC_MODE", "always_confirm")
    assert needs_user_confirmation(ExecTier.READ_LOCAL, auto_approve=False) is True


def test_strict_blocks_sudo(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "PENTESTLLM_EXEC_MODE", "strict")
    monkeypatch.setattr(Config, "PENTESTLLM_ALLOW_SUDO", False)
    blocked, _ = is_blocked(ExecTier.PRIVILEGED)
    assert blocked is True

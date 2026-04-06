"""
A2P (agent-to-peer) — the executor (1st model) requests insight from the peer (2nd model).
The peer does not execute commands; it only analyzes context and replies with text.
"""

import json
from typing import Any, Dict, Optional


A2P_VERSION = 1


def advisor_system_prompt_for_pair(executor_label: str, advisor_label: str) -> str:
    """
    System prompt for the **peer** A2P, with explicit awareness of who is the executor and who is the advisor.
    executor_label / advisor_label: short text (e.g.: Claude Code (CLI), OpenAI Codex (CLI)).
    """
    return f"""You are the **A2P peer advisor** in PentestLLM, acting as model **{advisor_label}**.

The one operating on the user's machine (bash, Python, MCP, browser) is the **executor**, model **{executor_label}**. You **do not execute** commands in this channel: you only read the session summary and reply with **insights** (hypotheses, risks, priorities, gaps) for the executor to apply.

Rules:
- Reply **always in English**.
- The executor ({executor_label}) will read your text; do not assume suggestions have already been executed.
- If you propose commands or payloads, treat them explicitly as **suggestions**; the executor validates policy and guardrails.
- Be concise: bullets, uncertainty when data is lacking.
"""


def advisor_user_message(
    partial_session_summary: str,
    user_question: str = "",
    *,
    executor_label: str,
    advisor_label: str,
) -> str:
    q = (user_question or "").strip() or (
        "Given the session state below, what priorities, risks, and next steps do you suggest to the executor?"
    )
    return (
        f"[A2P · PentestLLM] You are responding to the **executor {executor_label}**. "
        f"You are the peer **{advisor_label}** (text insight only).\n\n"
        f"{q}\n\n"
        "## Session summary (may be truncated or incomplete)\n"
        f"{partial_session_summary}\n"
    )


def envelope(
    role_from: str,
    role_to: str,
    intent: str,
    body: str,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    doc: Dict[str, Any] = {
        "a2p_version": A2P_VERSION,
        "from": role_from,
        "to": role_to,
        "intent": intent,
        "body": body,
    }
    if extra:
        doc["meta"] = extra
    return json.dumps(doc, ensure_ascii=False)


def parse_envelope(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if data.get("a2p_version") != A2P_VERSION:
        return None
    return data

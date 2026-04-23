from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from agents.definitions import AGENTS
from core.agent import Agent
from core.agent_team_state import SharedTeamState as AgentTeamSharedState
from core.agent_team_state import TeamStateError
from core.agent_team_state import TeamTask as AgentTeamTask
from core.agent_team_ui import AgentTeamUI
from utils.tokens import count_tokens
from utils.model_info import model_context_window, fmt_k
from utils.ui import console


NATIVE_WORKER_ORDER: List[Tuple[str, str]] = [
    ("recon_passive_agent", "Recon Passive"),
    ("recon_active_agent", "Recon Active"),
    ("code_review_agent", "Code Review"),
    ("vuln_scanner_agent", "Vulnerability Scanner"),
    ("api_testing_agent", "API Testing"),
    ("exploit_validation_agent", "Exploit Validation"),
    ("reporting_agent", "Reporting"),
]

WORKER_OBJECTIVES: Dict[str, str] = {
    "recon_passive_agent": "Perform passive intelligence collection and return prioritized assets with confidence notes.",
    "recon_active_agent": "Validate live hosts/services and enumerate endpoints with controlled scan intensity.",
    "code_review_agent": "Review source/configuration for exploitable weaknesses with file-level evidence.",
    "vuln_scanner_agent": "Run approved high-signal scanners and return validated candidate findings.",
    "api_testing_agent": "Assess API authorization and abuse paths using OWASP API Top 10 as reference.",
    "exploit_validation_agent": "Safely validate impact for prioritized findings and produce reproducible PoCs.",
    "reporting_agent": "Consolidate evidence, deduplicate findings, and prepare structured technical output.",
}


@dataclass
class WorkerRow:
    key: str
    role: str
    model: str
    status: str = "pending"
    note: str = ""
    log_path: Optional[Path] = None


class MultiAgentOrchestrator:
    def __init__(self, auth_manager, manager):
        self.auth_manager = auth_manager
        self.manager = manager
        self.last_session_dir: Optional[Path] = None
        self.last_report_path: Optional[Path] = None
        self.last_target: str = ""
        self.last_mode: str = "auto"
        self.last_selected_worker_keys: List[str] = []
        self.last_models: Dict[str, str] = {}

    @staticmethod
    def _manifest_path(session_dir: Path) -> Path:
        return session_dir / "session_manifest.json"

    @staticmethod
    def _load_manifest(session_dir: Path) -> Dict[str, object]:
        path = MultiAgentOrchestrator._manifest_path(session_dir)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _write_manifest(session_dir: Path, payload: Dict[str, object]) -> None:
        path = MultiAgentOrchestrator._manifest_path(session_dir)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def inspect_resumable_session(session_dir: str) -> Dict[str, object]:
        path = Path(session_dir).expanduser()
        details: Dict[str, object] = {
            "session_dir": str(path),
            "resumable": False,
            "errors": [],
            "manifest_path": str(MultiAgentOrchestrator._manifest_path(path)),
            "tasks_path": str(path / "team" / "tasks.json"),
            "mailbox_path": str(path / "team" / "mailbox.jsonl"),
            "counts": {},
            "selected_worker_keys": [],
            "manifest": {},
        }
        errors: List[str] = []

        if not path.exists():
            errors.append(f"Session directory not found: {path}")
            details["errors"] = errors
            return details
        if not path.is_dir():
            errors.append(f"Session path is not a directory: {path}")
            details["errors"] = errors
            return details

        manifest_path = MultiAgentOrchestrator._manifest_path(path)
        if not manifest_path.exists():
            errors.append(f"Session manifest missing: {manifest_path}")
        else:
            try:
                manifest_raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest_raw, dict):
                    errors.append(f"Session manifest has invalid payload type: {manifest_path}")
                    manifest: Dict[str, object] = {}
                else:
                    manifest = manifest_raw
                    details["manifest"] = manifest
            except Exception as e:
                errors.append(f"Session manifest is corrupt: {manifest_path} ({e})")
                manifest = {}

            selected_raw = manifest.get("selected_worker_keys", [])
            selected_keys: List[str] = []
            if isinstance(selected_raw, list):
                selected_keys = [str(k) for k in selected_raw if isinstance(k, str)]
            if not selected_keys:
                selected_keys = [key for key, _label in NATIVE_WORKER_ORDER if key in AGENTS]
            selected_workers = [
                key
                for key, _label in NATIVE_WORKER_ORDER
                if key in selected_keys and key in AGENTS
            ]
            details["selected_worker_keys"] = selected_workers
            if not selected_workers:
                errors.append("No resumable workers found in session manifest.")

        tasks_path = path / "team" / "tasks.json"
        if not tasks_path.exists():
            errors.append(f"Team tasks state file missing: {tasks_path}")
        else:
            try:
                tasks_payload = json.loads(tasks_path.read_text(encoding="utf-8"))
                if not isinstance(tasks_payload, dict):
                    errors.append(f"Team tasks state payload is invalid: {tasks_path}")
                tasks = tasks_payload.get("tasks", [])
                if not isinstance(tasks, list):
                    errors.append(f"Team tasks list is invalid: {tasks_path}")
                else:
                    counts: Dict[str, int] = {}
                    for idx, item in enumerate(tasks):
                        if not isinstance(item, dict):
                            errors.append(
                                f"Invalid task entry at index {idx} in state file: {tasks_path}"
                            )
                            continue
                        status = str(item.get("status", "pending"))
                        counts[status] = counts.get(status, 0) + 1
                    details["counts"] = counts
            except Exception as e:
                errors.append(f"Team tasks state file is corrupt: {tasks_path} ({e})")

        mailbox_path = path / "team" / "mailbox.jsonl"
        if not mailbox_path.exists():
            errors.append(f"Team mailbox state file missing: {mailbox_path}")
        else:
            try:
                lines = mailbox_path.read_text(encoding="utf-8").splitlines()
                for idx, line in enumerate(lines, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        errors.append(f"Invalid mailbox entry at line {idx} in: {mailbox_path}")
                        continue
                    for key in ("timestamp", "sender", "recipient", "message"):
                        if key not in payload:
                            errors.append(
                                f"Mailbox entry missing '{key}' at line {idx} in: {mailbox_path}"
                            )
                            break
            except Exception as e:
                errors.append(f"Team mailbox state file is corrupt: {mailbox_path} ({e})")

        details["errors"] = errors
        details["resumable"] = len(errors) == 0
        return details

    @staticmethod
    def _default_os_choice() -> str:
        system = platform.system().lower()
        if system == "darwin":
            return "MacOS"
        if system == "windows":
            return "Windows"
        return "Linux"

    @staticmethod
    def _build_session_dir(shared_project_dir: str) -> Path:
        now = time.strftime("%Y%m%d_%H%M%S")
        session_dir = Path(shared_project_dir) / "multi_sessions" / f"session_{now}"
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _ask_model(self, label: str, default_model: str) -> str:
        hints = (
            "gpt-4o, deepseek-chat, deepseek-reasoner, "
            "claude-sonnet-4-20250514, openai-codex-cli, claude-code-cli, auto-rotate-free"
        )
        console.print(f"[dim]{label} - examples: {hints}[/dim]")
        return Prompt.ask(f"Model for {label}", default=default_model).strip() or default_model

    def _quiz(
        self,
        target: str,
        default_model: str,
        mode: str,
        selected_workers: List[Tuple[str, str]],
        saved_quiz: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        # Offer to reuse a previously saved config
        if saved_quiz and isinstance(saved_quiz, dict) and saved_quiz.get("os_choice"):
            _prev_os = saved_quiz.get("os_choice", "?")
            _prev_model = list(saved_quiz.get("models", {}).values())[0] if saved_quiz.get("models") else "?"
            _prev_auto = "yes" if saved_quiz.get("auto_approve") else "no"
            _prev_native = "native" if saved_quiz.get("use_native") else "temporary"
            console.print(
                Panel(
                    f"Previous configuration found:\n"
                    f"  OS={_prev_os} | model={_prev_model} | auto_approve={_prev_auto} | profiles={_prev_native}",
                    title="Reuse previous config?",
                    border_style="yellow",
                )
            )
            if Confirm.ask("Reuse this configuration for the current run?", default=True):
                result = dict(saved_quiz)
                result["target"] = target
                # Ensure all current workers have model entries
                fallback_model = _prev_model if _prev_model != "?" else default_model
                for key, _ in selected_workers:
                    result.setdefault("models", {})[key] = result["models"].get(key, fallback_model)  # type: ignore[index]
                result.setdefault("models", {}).setdefault("pentest_brain_agent", fallback_model)
                return result

        console.print(
            Panel(
                "Multi-agent setup quiz\n"
                "Aligned with the Agent Teams model (lead + teammates + shared task list + mailbox).",
                title="Multi-Agent Setup",
                border_style="cyan",
            )
        )

        os_choice = Prompt.ask(
            "Runtime operating system",
            choices=["MacOS", "Linux", "Windows"],
            default=self._default_os_choice(),
        )

        distro = None
        if os_choice == "Linux":
            distro = Prompt.ask(
                "Linux distribution",
                choices=["Kali", "Ubuntu", "Debian", "Parrot", "Other"],
                default="Kali",
            )

        teammate_mode = Prompt.ask(
            "Teammate display mode",
            choices=["auto", "in-process", "split-panes"],
            default="auto",
        )

        auto_approve = Confirm.ask("Auto-approve commands for sub-agents?", default=False)
        require_plan_approval = Confirm.ask(
            "Require plan approval from teammates before executing each task?",
            default=False,
        )
        allow_installs = Confirm.ask("Allow package installation/removal?", default=False)
        allow_deletes = Confirm.ask("Allow destructive delete commands?", default=False)

        individual_models = Confirm.ask("Choose individual model per agent?", default=False)
        models: Dict[str, str] = {}

        if individual_models:
            models["pentest_brain_agent"] = self._ask_model("brain agent", default_model)
            for key, label in selected_workers:
                models[key] = self._ask_model(label, default_model)
        else:
            common_model = self._ask_model("all sub-agents", default_model)
            brain_model = self._ask_model("brain agent", common_model)
            models["pentest_brain_agent"] = brain_model
            for key, _ in selected_workers:
                models[key] = common_model

        use_native = mode == "native"
        if mode == "auto":
            use_temporary = Confirm.ask(
                "Create temporary sub-agents from prompt (deleted after completion)?",
                default=True,
            )
            use_native = not use_temporary

        open_iterm = False
        if teammate_mode in ("auto", "split-panes"):
            if os_choice == "MacOS" and self._iterm_supported():
                open_iterm = Confirm.ask(
                    "Open panes automatically in iTerm2 to monitor tasks?",
                    default=True,
                )
            elif os_choice == "Linux" and self._tmux_supported():
                open_iterm = Confirm.ask(
                    "Open panes automatically in tmux to monitor tasks?",
                    default=True,
                )
            elif os_choice == "Windows" and self._wt_supported():
                open_iterm = Confirm.ask(
                    "Open panes automatically in Windows Terminal to monitor tasks?",
                    default=True,
                )

        return {
            "target": target,
            "os_choice": os_choice,
            "distro": distro,
            "teammate_mode": teammate_mode,
            "auto_approve": auto_approve,
            "require_plan_approval": require_plan_approval,
            "allow_installs": allow_installs,
            "allow_deletes": allow_deletes,
            "models": models,
            "use_native": use_native,
            "open_iterm": open_iterm,
        }

    @staticmethod
    def _iterm_supported() -> bool:
        return platform.system().lower() == "darwin" and os.environ.get("TERM_PROGRAM") == "iTerm.app"

    @staticmethod
    def _tmux_supported() -> bool:
        """Return True when running inside a tmux session on Linux/macOS."""
        return bool(os.environ.get("TMUX")) and platform.system().lower() != "windows"

    @staticmethod
    def _wt_supported() -> bool:
        """Return True when Windows Terminal (wt.exe) is available on Windows."""
        if platform.system().lower() != "windows":
            return False
        try:
            result = subprocess.run(
                ["where", "wt"],
                check=False,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _split_wt(command: str) -> bool:
        """Open a Windows Terminal split pane running *command*. Returns True on success."""
        try:
            subprocess.run(
                ["wt", "split-pane", "--", "cmd", "/c", command],
                check=False,
                capture_output=True,
                text=True,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _split_tmux(command: str) -> bool:
        """Open a new tmux split pane running *command*. Returns True on success."""
        try:
            subprocess.run(
                ["tmux", "split-window", "-h", command],
                check=False,
                capture_output=True,
                text=True,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _split_iterm2(vertical: bool, command: str) -> bool:
        split_dir = "vertically" if vertical else "horizontally"
        script = f'''
        tell application "iTerm2"
          if (count of windows) = 0 then
            create window with default profile
          end if
          tell current window
            tell current session
              set newSession to (split {split_dir} with default profile)
              tell newSession
                write text {json.dumps(command)}
              end tell
            end tell
          end tell
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
            return True
        except Exception:
            return False

    def _open_iterm_views(self, workers: List[WorkerRow], session_dir: Path) -> None:
        system = platform.system().lower()
        use_iterm = self._iterm_supported()
        use_tmux = not use_iterm and self._tmux_supported()
        use_wt = not use_iterm and not use_tmux and self._wt_supported()

        if not use_iterm and not use_tmux and not use_wt:
            hint = "PowerShell" if system == "windows" else "iTerm2 / tmux"
            console.print(
                f"[dim]No supported terminal multiplexer detected ({hint}). "
                f"Tail worker logs manually: {session_dir}/<worker>.log[/dim]"
            )
            return

        max_panes = min(len(workers), 4)
        for idx, row in enumerate(workers[:max_panes]):
            if not row.log_path:
                continue
            row.log_path.touch(exist_ok=True)
            if system == "windows":
                cmd = f"powershell -NoExit -Command Get-Content -Wait {json.dumps(str(row.log_path))}"
            else:
                cmd = (
                    f"cd {json.dumps(str(session_dir))} && clear && "
                    f"echo '[{row.role}] monitor' && tail -f {json.dumps(str(row.log_path))}"
                )
            if idx == 0:
                continue
            if use_iterm:
                ok = self._split_iterm2(vertical=(idx % 2 == 1), command=cmd)
                if not ok:
                    console.print(f"[yellow]Failed to open iTerm2 pane for {row.role}.[/yellow]")
            elif use_tmux:
                ok = self._split_tmux(command=cmd)
                if not ok:
                    console.print(f"[yellow]Failed to open tmux pane for {row.role}.[/yellow]")
            else:
                ok = self._split_wt(command=cmd)
                if not ok:
                    console.print(f"[yellow]Failed to open Windows Terminal pane for {row.role}.[/yellow]")

    @staticmethod
    def _build_task_graph(selected_workers: List[Tuple[str, str]]) -> List[AgentTeamTask]:
        worker_keys = {k for k, _ in selected_workers}
        tasks: List[AgentTeamTask] = []

        if "recon_passive_agent" in worker_keys:
            tasks.append(
                AgentTeamTask(
                    task_id="T1",
                    role_key="recon_passive_agent",
                    title="Passive intelligence collection and asset correlation",
                )
            )

        if "recon_active_agent" in worker_keys:
            tasks.append(
                AgentTeamTask(
                    task_id="T2",
                    role_key="recon_active_agent",
                    title="Active host/service discovery and endpoint enumeration",
                )
            )

        if "code_review_agent" in worker_keys:
            tasks.append(
                AgentTeamTask(
                    task_id="T3",
                    role_key="code_review_agent",
                    title="Source-assisted security review",
                )
            )

        if "vuln_scanner_agent" in worker_keys:
            deps = ["T2"] if any(t.task_id == "T2" for t in tasks) else []
            tasks.append(
                AgentTeamTask(
                    task_id="T4",
                    role_key="vuln_scanner_agent",
                    title="Automated vulnerability scanning and triage",
                    dependencies=deps,
                )
            )

        if "api_testing_agent" in worker_keys:
            deps = ["T2"] if any(t.task_id == "T2" for t in tasks) else []
            tasks.append(
                AgentTeamTask(
                    task_id="T5",
                    role_key="api_testing_agent",
                    title="OWASP API Top 10 targeted validation",
                    dependencies=deps,
                )
            )

        if "exploit_validation_agent" in worker_keys:
            deps: List[str] = []
            for candidate in ("T3", "T4", "T5"):
                if any(t.task_id == candidate for t in tasks):
                    deps.append(candidate)
            tasks.append(
                AgentTeamTask(
                    task_id="T6",
                    role_key="exploit_validation_agent",
                    title="Controlled exploitation and impact validation",
                    dependencies=deps,
                )
            )

        if "reporting_agent" in worker_keys:
            deps = [t.task_id for t in tasks if t.role_key != "reporting_agent"]
            tasks.append(
                AgentTeamTask(
                    task_id="T7",
                    role_key="reporting_agent",
                    title="Deduplicate findings and compile technical report",
                    dependencies=deps,
                )
            )

        return tasks

    async def _brain_plan(self, brain: Agent, target: str, user_objective: str) -> str:
        prompt = (
            "Create a concise lead plan for an agent team with shared tasks. "
            "Return short bullets with task sequencing, dependency awareness, and evidence standards.\n\n"
            f"Target: {target}\n"
            f"Objective: {user_objective or 'Full PTES/OWASP-aligned pentest execution.'}\n"
        )
        messages = [
            {"role": "system", "content": brain.system_prompt},
            {"role": "user", "content": prompt},
        ]
        return await brain.llm.generate(messages)

    async def _lead_plan_approval(
        self,
        brain: Agent,
        worker_label: str,
        task: AgentTeamTask,
        plan_text: str,
    ) -> Tuple[bool, str]:
        prompt = (
            "Review the teammate plan and decide APPROVE or REJECT. "
            "Reply in first line with APPROVE or REJECT, then max 4 bullets of feedback.\n\n"
            f"Teammate: {worker_label}\n"
            f"Task: {task.task_id} - {task.title}\n"
            f"Plan:\n{plan_text[:6000]}\n"
        )
        decision = await brain.llm.generate(
            [
                {"role": "system", "content": brain.system_prompt},
                {"role": "user", "content": prompt},
            ]
        )
        head = (decision or "").strip().splitlines()[0].upper()
        approved = head.startswith("APPROVE")
        return approved, decision

    @staticmethod
    def _compose_worker_prompt(
        worker_key: str,
        target: str,
        user_objective: str,
        brain_plan: str,
        task: AgentTeamTask,
        os_choice: str,
        distro: Optional[str],
        inbox: List[Dict[str, str]],
    ) -> str:
        os_desc = os_choice if os_choice != "Linux" else f"Linux ({distro or 'Kali'})"
        stage_goal = WORKER_OBJECTIVES.get(worker_key, "Execute your specialist phase and report evidence.")
        inbox_text = "\n".join(
            [f"- [{m['sender']}] {m['message'][:400]}" for m in inbox[-5:]]
        ) or "- No new team messages."

        return (
            f"Primary target: {target}\n"
            f"Operator objective: {user_objective or 'Execute a complete PTES/OWASP pentest.'}\n"
            f"Runtime operating system: {os_desc}\n\n"
            f"Lead plan:\n{brain_plan}\n\n"
            f"Current task (shared list): {task.task_id} - {task.title}\n"
            f"This role objective: {stage_goal}\n\n"
            f"Recent mailbox messages:\n{inbox_text}\n\n"
            "Mandatory rules:\n"
            "- Respect scope and authorization.\n"
            "- No package install/removal by default.\n"
            "- No destructive commands by default.\n"
            "- Report concise, actionable evidence with next step.\n"
        )

    @staticmethod
    def _build_temporary_worker_profiles(
        selected_workers: List[Tuple[str, str]],
        target: str,
        user_objective: str,
        brain_plan: str,
        os_choice: str,
        distro: Optional[str],
    ) -> Dict[str, Dict[str, str]]:
        os_desc = os_choice if os_choice != "Linux" else f"Linux ({distro or 'Kali'})"
        base_objective = user_objective or "Execute a PTES/OWASP pentest with reproducible evidence."
        shared_rules = (
            "Global safety rules:\n"
            "- Explicit scope and authorization are mandatory.\n"
            "- No package install/removal by default.\n"
            "- No destructive commands by default.\n"
            "- Work only within the designated workspace.\n"
            "- If a tool is missing, request operator approval before installing.\n"
        )
        profiles: Dict[str, Dict[str, str]] = {}
        for worker_key, label in selected_workers:
            stage_goal = WORKER_OBJECTIVES.get(
                worker_key,
                "Execute the assigned phase with focus on evidence and validated attack chain.",
            )
            profiles[worker_key] = {
                "description": f"Temporary runtime profile for {label}",
                "system_prompt": (
                    f"You are {label} (temporary runtime teammate profile).\n\n"
                    "Role:\n"
                    f"- {stage_goal}\n\n"
                    "Engagement context:\n"
                    f"- Target: {target}\n"
                    f"- Operator objective: {base_objective}\n"
                    f"- Runtime OS: {os_desc}\n\n"
                    "Lead baseline plan:\n"
                    f"{brain_plan}\n\n"
                    f"{shared_rules}\n"
                    "Deliverables:\n"
                    "- Concise evidence summary\n"
                    "- Confirmed findings or validated negatives\n"
                    "- Next-step recommendations for teammate handoff\n"
                ),
            }
        return profiles

    async def _execute_session(
        self,
        *,
        target: str,
        user_objective: str,
        available_mcps: Dict[str, object],
        mode: str,
        selected_workers: List[Tuple[str, str]],
        quiz: Dict[str, object],
        session_dir: Path,
        resume_existing: bool = False,
    ) -> str:
        fallback_model = str(
            (quiz.get("models", {}) or {}).get("pentest_brain_agent")
            or "gpt-4o"
        )
        available_workers: List[Tuple[str, str]] = []
        for key, label in NATIVE_WORKER_ORDER:
            if key in AGENTS:
                available_workers.append((key, label))

        workers_rows: List[WorkerRow] = []
        workers_rows.append(
            WorkerRow(
                key="brain",
                role="Pentest Brain",
                model=str(quiz["models"]["pentest_brain_agent"]),
                status="pending",
                log_path=session_dir / "brain.log",
            )
        )
        for key, label in selected_workers:
            workers_rows.append(
                WorkerRow(
                    key=key,
                    role=label,
                    model=str(quiz["models"].get(key, fallback_model)),
                    status="pending",
                    log_path=session_dir / f"{key}.log",
                )
            )

        team_name = f"pentest-team-{time.strftime('%H%M%S')}"
        team_state = AgentTeamSharedState(
            session_dir=session_dir,
            team_name=team_name,
            lead_name="pentest_brain",
            members=selected_workers,
            teammate_mode=str(quiz["teammate_mode"]),
            require_plan_approval=bool(quiz["require_plan_approval"]),
            require_existing_state=resume_existing,
        )

        if resume_existing:
            resumed_ids = await team_state.prepare_for_resume()
            if resumed_ids:
                console.print(
                    f"[yellow]Resume: reset in-progress tasks to pending:[/yellow] {', '.join(resumed_ids)}"
                )
        else:
            for t in self._build_task_graph(selected_workers):
                await team_state.add_task(t)

        if quiz["open_iterm"]:
            self._open_iterm_views(workers_rows, session_dir)

        brain_cfg = AGENTS["pentest_brain_agent"]
        brain_dir = session_dir / "brain"
        brain_dir.mkdir(parents=True, exist_ok=True)

        brain = Agent(
            name="pentest_brain",
            model=str(quiz["models"]["pentest_brain_agent"]),
            system_prompt=brain_cfg["system_prompt"],
            mcp_clients=list(available_mcps.values()),
            auto_approve=bool(quiz["auto_approve"]),
            limit=10,
            project_dir=str(brain_dir),
            auth_manager=self.auth_manager,
            allow_installs=bool(quiz["allow_installs"]),
            allow_deletes=bool(quiz["allow_deletes"]),
            runtime_os=str(quiz["os_choice"]),
            runtime_distro=quiz["distro"],
        )

        workers: Dict[str, Agent] = {}

        def _team_metrics() -> Dict[str, object]:
            runtime_agents: List[Tuple[str, Agent]] = [("brain", brain)]
            runtime_agents.extend(
                [
                    (worker_key, worker_agent)
                    for worker_key, worker_agent in workers.items()
                    if worker_agent is not None
                ]
            )
            metrics_agents = []
            total_context_injections = 0
            total_context_docs = 0
            for key, runtime_agent in runtime_agents:
                try:
                    used = count_tokens(runtime_agent.history, runtime_agent.llm.model)
                except Exception:
                    used = 0
                max_ctx = int(
                    getattr(
                        runtime_agent,
                        "max_context_tokens",
                        model_context_window(runtime_agent.llm.model),
                    )
                )
                pct = (used * 100.0 / max_ctx) if max_ctx else 0.0
                ctx_injections = int(
                    getattr(runtime_agent, "context_injection_count", 0) or 0
                )
                ctx_docs = int(getattr(runtime_agent, "context_docs_loaded", 0) or 0)
                total_context_injections += ctx_injections
                total_context_docs += ctx_docs
                metrics_agents.append(
                    {
                        "label": key,
                        "used": fmt_k(int(used)),
                        "max": fmt_k(max_ctx),
                        "pct": pct,
                        "ctx_injections": ctx_injections,
                        "ctx_docs": ctx_docs,
                        "actions": int(getattr(runtime_agent, "action_count", 0) or 0),
                    }
                )
            brain_model = str(quiz["models"]["pentest_brain_agent"])
            return {
                "executor_context_window": fmt_k(
                    model_context_window(brain_model)
                ),
                "peer_context_window": fmt_k(
                    model_context_window(brain_model)
                ),
                "total_context_injections": total_context_injections,
                "total_context_docs": total_context_docs,
                "agents": metrics_agents,
            }

        board = AgentTeamUI(
            title=f"Agent Team - {target}",
            workers=workers_rows,
            team_state=team_state,
            metrics_provider=_team_metrics,
        )

        board.update_worker("brain", "running", "creating team lead plan")
        if resume_existing:
            manifest = self._load_manifest(session_dir)
            brain_plan = str(manifest.get("brain_plan", "")).strip()
            if not brain_plan:
                brain_plan = await self._brain_plan(brain, target=target, user_objective=user_objective)
        else:
            brain_plan = await self._brain_plan(brain, target=target, user_objective=user_objective)
            await team_state.send_message("lead", "*", f"Lead baseline plan:\n{brain_plan[:3000]}")
        board.update_worker("brain", "running", "delegating tasks")

        temporary_profiles: Dict[str, Dict[str, str]] = {}
        temporary_profiles_path: Optional[Path] = None
        if not bool(quiz["use_native"]):
            temporary_profiles = self._build_temporary_worker_profiles(
                selected_workers=selected_workers,
                target=target,
                user_objective=user_objective,
                brain_plan=brain_plan,
                os_choice=str(quiz["os_choice"]),
                distro=quiz["distro"],
            )
            temporary_profiles_path = session_dir / "temporary_profiles.json"
            temporary_profiles_path.write_text(
                json.dumps(temporary_profiles, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            board.update_worker("brain", "running", "temporary profiles generated")

        self._write_manifest(
            session_dir,
            {
                "target": target,
                "user_objective": user_objective,
                "mode": mode,
                "selected_worker_keys": [key for key, _label in selected_workers],
                "models": dict(quiz["models"]),
                "use_native": bool(quiz["use_native"]),
                "os_choice": quiz["os_choice"],
                "distro": quiz["distro"],
                "auto_approve": bool(quiz["auto_approve"]),
                "require_plan_approval": bool(quiz["require_plan_approval"]),
                "allow_installs": bool(quiz["allow_installs"]),
                "allow_deletes": bool(quiz["allow_deletes"]),
                "teammate_mode": quiz["teammate_mode"],
                "open_iterm": bool(quiz["open_iterm"]),
                "brain_plan": brain_plan,
                "status": "running",
                "updated_at": time.time(),
            },
        )

        # Persist session state early for auto-resume on crash (Item C)
        try:
            from utils.session_state import save_session_state as _save_ss
            _save_ss({
                "last_orchestrated_session": {
                    "session_dir": str(session_dir),
                    "target": target,
                    "mode": mode,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
            })
        except Exception:
            pass

        async def run_worker(worker_key: str, label: str):
            worker_cfg = AGENTS[worker_key]
            if bool(quiz["use_native"]):
                worker_system_prompt = worker_cfg["system_prompt"]
            else:
                worker_system_prompt = (
                    temporary_profiles.get(worker_key, {}).get("system_prompt")
                    or worker_cfg["system_prompt"]
                )
            worker_dir = session_dir / worker_key
            worker_dir.mkdir(parents=True, exist_ok=True)

            agent = Agent(
                name=worker_key,
                model=str(quiz["models"].get(worker_key, fallback_model)),
                system_prompt=worker_system_prompt,
                mcp_clients=list(available_mcps.values()),
                auto_approve=bool(quiz["auto_approve"]),
                limit=14,
                project_dir=str(worker_dir),
                auth_manager=self.auth_manager,
                allow_installs=bool(quiz["allow_installs"]),
                allow_deletes=bool(quiz["allow_deletes"]),
                runtime_os=str(quiz["os_choice"]),
                runtime_distro=quiz["distro"],
            )
            workers[worker_key] = agent
            board.update_worker(worker_key, "running", "waiting for claimable task")

            while True:
                task = await team_state.claim_next_for_role(worker_key, claimant=label)
                if task is None:
                    has_open = await team_state.has_open_for_role(worker_key)
                    if not has_open:
                        board.update_worker(worker_key, "completed", "no remaining tasks")
                        return
                    board.update_worker(worker_key, "running", "blocked by dependencies")
                    await asyncio.sleep(0.5)
                    continue

                board.update_worker(worker_key, "running", f"claimed {task.task_id}")
                inbox = await team_state.pull_inbox(worker_key)

                if quiz["require_plan_approval"]:
                    plan_prompt = (
                        f"Create a concise implementation plan for task {task.task_id} - {task.title}. "
                        "No execution, plan only, include quality gates and risk controls."
                    )
                    plan_text = await agent.llm.generate(
                        [
                            {"role": "system", "content": agent.system_prompt},
                            {"role": "user", "content": plan_prompt},
                        ]
                    )
                    approved, feedback = await self._lead_plan_approval(brain, label, task, plan_text)
                    if not approved:
                        retry_plan_prompt = (
                            f"Plan was rejected by lead. Feedback:\n{feedback[:3000]}\n\n"
                            "Revise the plan and address each concern."
                        )
                        plan_text = await agent.llm.generate(
                            [
                                {"role": "system", "content": agent.system_prompt},
                                {"role": "user", "content": retry_plan_prompt},
                            ]
                        )
                        approved, feedback = await self._lead_plan_approval(brain, label, task, plan_text)
                    if not approved:
                        await team_state.fail_task(task.task_id, f"Plan not approved by lead: {feedback[:600]}")
                        board.update_worker(worker_key, "failed", f"plan rejected for {task.task_id}")
                        await team_state.send_message(
                            "lead",
                            worker_key,
                            f"Task {task.task_id} blocked: plan rejected. Feedback:\n{feedback[:1200]}",
                        )
                        continue

                worker_prompt = self._compose_worker_prompt(
                    worker_key=worker_key,
                    target=target,
                    user_objective=user_objective,
                    brain_plan=brain_plan,
                    task=task,
                    os_choice=str(quiz["os_choice"]),
                    distro=quiz["distro"],
                    inbox=inbox,
                )

                try:
                    board.update_worker(worker_key, "running", f"executing {task.task_id}")
                    await agent.process_message(worker_prompt)
                    summary = await agent.stop()
                    await team_state.complete_task(task.task_id, summary)
                    board.update_worker(worker_key, "running", f"{task.task_id} completed")
                    await team_state.send_message(
                        worker_key,
                        "lead",
                        f"Completed {task.task_id}: {summary[:1200]}",
                    )

                    lead_feedback = await brain.llm.generate(
                        [
                            {"role": "system", "content": brain.system_prompt},
                            {
                                "role": "user",
                                "content": (
                                    f"Teammate {label} completed {task.task_id}. "
                                    f"Summary:\n{summary[:3500]}\n\n"
                                    "Return up to 3 actionable bullets for remaining teammates."
                                ),
                            },
                        ]
                    )
                    await team_state.send_message("lead", "*", lead_feedback[:1800])
                except Exception as e:
                    await team_state.fail_task(task.task_id, str(e))
                    board.update_worker(worker_key, "failed", f"{task.task_id} failed")
                    await team_state.send_message(
                        worker_key,
                        "lead",
                        f"Failed {task.task_id}: {str(e)[:800]}",
                    )

        worker_tasks = [
            asyncio.create_task(run_worker(worker_key=k, label=label))
            for k, label in selected_workers
        ]

        with Live(board.render(), console=console, refresh_per_second=4) as live:
            board.start_input_capture()
            try:
                async def _drain_runtime_queue() -> None:
                    runtime_msgs = board.pop_runtime_instructions()
                    if not runtime_msgs:
                        return
                    for msg in runtime_msgs:
                        lead_msg = f"Operator runtime instruction: {msg}"
                        await team_state.send_message("operator", "lead", lead_msg)
                        await team_state.send_message("lead", "*", lead_msg)
                        brain.history.append(
                            {
                                "role": "user",
                                "content": f"[OPERATOR RUNTIME INSTRUCTION]\n{msg}",
                            }
                        )
                        # Forward instruction to running worker agents' preemption queues
                        for wk, worker_agent in workers.items():
                            if board.workers[wk].status == "running":
                                worker_agent.submit_instruction(msg)
                        board.update_worker("brain", "running", "runtime instruction queued")

                interrupted = False
                pending = set(worker_tasks)
                try:
                    while pending:
                        board.poll_input()
                        await _drain_runtime_queue()
                        done, pending = await asyncio.wait(
                            pending,
                            timeout=0.5,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        _ = done
                        board.poll_input()
                        await _drain_runtime_queue()
                        live.update(board.render())
                except (KeyboardInterrupt, asyncio.CancelledError):
                    interrupted = True
                    console.print(
                        "\n[yellow]Ctrl+C received — stopping workers and persisting state…[/yellow]"
                    )
                    for t in worker_tasks:
                        if not t.done():
                            t.cancel()
                    await asyncio.gather(*worker_tasks, return_exceptions=True)
                    for wk in workers:
                        if board.workers[wk].status == "running":
                            board.update_worker(wk, "paused", "interrupted by operator")

                if not interrupted:
                    if worker_tasks:
                        await asyncio.gather(*worker_tasks, return_exceptions=True)
                        board.poll_input()
                        await _drain_runtime_queue()
                        live.update(board.render())

                    board.update_worker("brain", "running", "consolidating team output")
                    all_task_payload = {
                        task_id: {
                            "title": t.title,
                            "role_key": t.role_key,
                            "status": t.status,
                            "summary": t.summary,
                            "error": t.error,
                        }
                        for task_id, t in team_state.tasks.items()
                    }
                    final_summary = await brain.llm.generate(
                        [
                            {"role": "system", "content": brain.system_prompt},
                            {
                                "role": "user",
                                "content": (
                                    "Produce final lead report for this agent team run. "
                                    "Include: phase progression, key findings, unresolved gaps, and next steps.\n\n"
                                    f"Target: {target}\n"
                                    f"Objective: {user_objective or 'PTES/OWASP full flow'}\n"
                                    f"Tasks: {json.dumps(all_task_payload, ensure_ascii=False)[:35000]}"
                                ),
                            },
                        ]
                    )
                    board.update_worker("brain", "completed", "final summary ready")
                    board.poll_input()
                    live.update(board.render())
                else:
                    final_summary = (
                        f"Session interrupted by operator (Ctrl+C). Target: {target}\n"
                        "Use /session resume to continue from where workers left off."
                    )
                    board.update_worker("brain", "paused", "interrupted — session persisted")
                    live.update(board.render())
            finally:
                board.stop_input_capture()

        report_path = session_dir / "brain_final_summary.md"
        report_path.write_text(final_summary, encoding="utf-8")
        self.last_session_dir = session_dir
        self.last_report_path = report_path
        self.last_target = target
        self.last_mode = mode
        self.last_selected_worker_keys = [key for key, _label in selected_workers]
        self.last_models = {str(k): str(v) for k, v in dict(quiz["models"]).items()}

        if not interrupted:
            try:
                await team_state.cleanup()
                cleanup_result = "Team cleanup complete."
            except Exception as e:
                cleanup_result = f"Cleanup warning: {e}"

            if temporary_profiles_path and temporary_profiles_path.exists():
                try:
                    temporary_profiles_path.unlink()
                except Exception:
                    pass

        manifest_status = "interrupted" if interrupted else "completed"
        self._write_manifest(
            session_dir,
            {
                "target": target,
                "user_objective": user_objective,
                "mode": mode,
                "selected_worker_keys": [key for key, _label in selected_workers],
                "models": dict(quiz["models"]),
                "use_native": bool(quiz["use_native"]),
                "os_choice": quiz["os_choice"],
                "distro": quiz["distro"],
                "auto_approve": bool(quiz["auto_approve"]),
                "require_plan_approval": bool(quiz["require_plan_approval"]),
                "allow_installs": bool(quiz["allow_installs"]),
                "allow_deletes": bool(quiz["allow_deletes"]),
                "teammate_mode": quiz["teammate_mode"],
                "open_iterm": bool(quiz["open_iterm"]),
                "brain_plan": brain_plan,
                "status": manifest_status,
                "report_path": str(report_path),
                "updated_at": time.time(),
            },
        )

        if not interrupted:
            cleanup_note = (
                "Temporary teammates were generated for this run and released after completion."
                if not quiz["use_native"]
                else "Native profiles were used (definitions remain immutable in agents/configs)."
            )
            console.print(
                Panel(
                    f"Summary path: {report_path}\n{cleanup_result}\n{cleanup_note}",
                    title="/multi_agents",
                    border_style="green",
                )
            )

        return final_summary

    async def run(
        self,
        target: str,
        default_model: str,
        available_mcps: Dict[str, object],
        mode: str = "auto",
        user_objective: str = "",
        selected_worker_keys: Optional[List[str]] = None,
    ) -> str:
        if "pentest_brain_agent" not in AGENTS:
            raise RuntimeError("Missing agent config: pentest_brain_agent")

        available_workers: List[Tuple[str, str]] = []
        for key, label in NATIVE_WORKER_ORDER:
            if key in AGENTS:
                available_workers.append((key, label))

        selected_workers: List[Tuple[str, str]] = []
        if selected_worker_keys:
            selected_set = set(selected_worker_keys)
            for key, label in available_workers:
                if key in selected_set:
                    selected_workers.append((key, label))
        else:
            selected_workers = list(available_workers)

        if not selected_workers:
            raise RuntimeError("No valid workers selected for orchestrated run.")

        # Load previously saved quiz config for reuse offer
        _saved_quiz: Optional[Dict[str, object]] = None
        try:
            from utils.session_state import load_session_state as _load_ss
            _ss = _load_ss()
            _candidate = _ss.get("quiz_config") or {}
            if isinstance(_candidate, dict) and _candidate.get("os_choice"):
                _saved_quiz = _candidate
        except Exception:
            pass

        quiz = self._quiz(
            target=target,
            default_model=default_model,
            mode=mode,
            selected_workers=selected_workers,
            saved_quiz=_saved_quiz,
        )

        # Persist quiz config for next run (exclude target-specific / transient fields)
        try:
            from utils.session_state import save_session_state as _save_ss
            _save_ss({
                "quiz_config": {
                    "os_choice": quiz.get("os_choice"),
                    "distro": quiz.get("distro"),
                    "teammate_mode": quiz.get("teammate_mode"),
                    "auto_approve": bool(quiz.get("auto_approve", False)),
                    "require_plan_approval": bool(quiz.get("require_plan_approval", False)),
                    "allow_installs": bool(quiz.get("allow_installs", False)),
                    "allow_deletes": bool(quiz.get("allow_deletes", False)),
                    "use_native": bool(quiz.get("use_native", False)),
                    "open_iterm": bool(quiz.get("open_iterm", False)),
                    "models": dict(quiz.get("models", {})),
                },
            })
        except Exception:
            pass

        session_dir = self._build_session_dir(self.manager.shared_project_dir)
        return await self._execute_session(
            target=target,
            user_objective=user_objective,
            available_mcps=available_mcps,
            mode=mode,
            selected_workers=selected_workers,
            quiz=quiz,
            session_dir=session_dir,
            resume_existing=False,
        )

    async def resume(
        self,
        session_dir: str,
        available_mcps: Dict[str, object],
    ) -> str:
        details = self.inspect_resumable_session(session_dir)
        if not details.get("resumable", False):
            errors = details.get("errors", [])
            if isinstance(errors, list) and errors:
                raise RuntimeError("Session is not resumable:\n- " + "\n- ".join(str(e) for e in errors))
            raise RuntimeError(f"Session is not resumable: {session_dir}")

        path = Path(str(details["session_dir"]))
        manifest = details.get("manifest", {})
        if not isinstance(manifest, dict):
            manifest = {}

        selected_raw = details.get("selected_worker_keys", [])
        selected_keys = [str(k) for k in selected_raw] if isinstance(selected_raw, list) else []
        selected_workers = [
            (key, label) for key, label in NATIVE_WORKER_ORDER if key in selected_keys and key in AGENTS
        ]
        if not selected_workers:
            raise RuntimeError("No resumable workers found in session manifest.")

        models = manifest.get("models", {})
        if not isinstance(models, dict):
            models = {}
        fallback_model = str(
            models.get("pentest_brain_agent")
            or next((str(v) for v in models.values() if str(v).strip()), "gpt-4o")
        )
        models.setdefault("pentest_brain_agent", fallback_model)
        for key, _label in selected_workers:
            models.setdefault(key, fallback_model)

        quiz = {
            "target": manifest.get("target", ""),
            "os_choice": manifest.get("os_choice", self._default_os_choice()),
            "distro": manifest.get("distro"),
            "teammate_mode": manifest.get("teammate_mode", "auto"),
            "auto_approve": bool(manifest.get("auto_approve", False)),
            "require_plan_approval": bool(manifest.get("require_plan_approval", False)),
            "allow_installs": bool(manifest.get("allow_installs", False)),
            "allow_deletes": bool(manifest.get("allow_deletes", False)),
            "models": dict(models),
            "use_native": bool(manifest.get("use_native", True)),
            "open_iterm": bool(manifest.get("open_iterm", False)),
        }
        try:
            return await self._execute_session(
                target=str(manifest.get("target", "")),
                user_objective=str(manifest.get("user_objective", "")),
                available_mcps=available_mcps,
                mode=str(manifest.get("mode", "auto")),
                selected_workers=selected_workers,
                quiz=quiz,
                session_dir=path,
                resume_existing=True,
            )
        except TeamStateError as e:
            raise RuntimeError(str(e)) from e

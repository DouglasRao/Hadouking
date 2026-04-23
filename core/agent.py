import os
import json
import asyncio
import time
import platform
import hashlib
import tempfile
from typing import List, Dict, Any, Optional
from collections import deque
from datetime import datetime
import re
from config import Config
from .llm import LLM
from .guardrails import Guardrails
from .execution_policy import (
    classify_command,
    classify_python_script,
    exec_mode,
    is_blocked,
    needs_user_confirmation,
    policy_summary_for_prompt,
)
from utils.tools import execute_command
from utils.context_compress import maybe_compress_for_llm
from utils.ui import print_agent_step, ask_command_approval, ThinkingStatus, model_display_label
from utils.tokens import count_tokens
from utils.approval_state import ApprovalState
from .mcp import MCPClient
from .analyzer import OutputAnalyzer
from .browser import BrowserManager

from agents.context.loader import get_loader
from agents.tools.validator import get_validator

from .report_generator import ReportGenerator
from core.project_manager import ProjectManager

class Agent:
    def __init__(
        self,
        name,
        model,
        system_prompt,
        mcp_clients: List[MCPClient] = None,
        output_analyzer: OutputAnalyzer = None,
        auto_approve=False,
        limit=10,
        use_browser=False,
        headless=True,
        browser_intelligence=False,
        project_dir: str = None,
        auth_manager=None,
        allow_installs: bool = False,
        allow_deletes: bool = False,
        runtime_os: Optional[str] = None,
        runtime_distro: Optional[str] = None,
    ):
        self.name = name
        self.model = model
        self.system_prompt = system_prompt
        self.mcp_clients = mcp_clients or []
        self.history = [
            {
                "role": "system",
                "content": system_prompt + Config.system_prompt_locale_suffix(),
            }
        ]
        self.auto_approve = auto_approve
        self._approval_session_id = (
            f"{self.name}:{int(time.time() * 1000)}:{id(self)}"
        )
        self._session_auto_approve = False
        self.approval_state = ApprovalState(project_dir)
        self.approval_state.set_session(self._approval_session_id)
        self.limit = limit
        self.action_count = 0
        self.active = True
        self._stopped = False
        self._paused = False
        self.auth_manager = auth_manager
        self.allow_installs = allow_installs
        self.allow_deletes = allow_deletes
        self.runtime_os = runtime_os or platform.system()
        self.runtime_distro = runtime_distro
        self.max_context_tokens = 200000  # Increased to support modern LLMs (deepseek, claude, etc.)
        self.compaction_threshold = 0.90  # Compact at 90% to preserve more context
        self.use_browser = use_browser
        self.browser_intelligence = browser_intelligence
        self.context_injection_count = 0
        self.context_docs_loaded = 0
        
        # Initialize Project Manager
        if project_dir:
            # Use shared project directory
            self.project_dir = project_dir
        else:
            # Create new project directory
            pm = ProjectManager()
            self.project_dir = pm.create_new_project()
            print_agent_step(
                self.name,
                "Project",
                f"Project initialized at: {self.project_dir}",
                model=self.model,
            )

        # Initialize Report Generator
        self.report_generator = ReportGenerator(agent_name=name, target="Pending...")
        
        # Initialize Context System
        self.context_loader = get_loader()
        self.tool_validator = get_validator()
        
        # Initialize Output Analyzer
        self.output_analyzer = output_analyzer or OutputAnalyzer(
            model_name=model, auth_manager=auth_manager
        )
        
        # Initialize Browser Manager
        self.browser_manager = None
        if use_browser:
            self.browser_manager = BrowserManager(headless=headless, use_vision=browser_intelligence)
            print_agent_step(
                self.name,
                "Browser",
                "Browser manager started.",
                model=self.model,
            )

        # Initialize LLM
        self.llm = LLM(model, auth_manager=auth_manager)
        
        # Loop Detection
        self.command_history = deque(maxlen=10)
        self.loop_count = 0

        # Preemption / Interruption Queue (Item A)
        self._instruction_queue: asyncio.Queue = asyncio.Queue()
        self._pending_instruction: Optional[str] = None
        
        # Validate browser intelligence
        if browser_intelligence and not use_browser:
            raise ValueError("browser_intelligence requires use_browser=True")
        if self.browser_intelligence and not self.llm.supports_vision():
            raise ValueError(
                f"Model {model} does not support vision. Use gpt-4o, Claude API vision models, or gemini via OpenRouter."
            )

        # Inject MCP tools into system prompt
        self._inject_mcp_tools()
        if self.use_browser:
            self._inject_browser_tools()
            
        # Inject Tool Context
        self._inject_tool_context()

    def _step(self, step_type: str, content):
        """Step panel with model label (Claude CLI, Codex, API…)."""
        print_agent_step(self.name, step_type, content, model=self.model)

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def submit_instruction(self, instruction: str):
        """Queue a runtime instruction to reorient the agent at the next safe checkpoint."""
        self._instruction_queue.put_nowait(instruction)

    async def _drain_instruction_queue(self) -> bool:
        """Check for runtime instructions. Returns True if instruction was injected."""
        try:
            instruction = self._instruction_queue.get_nowait()
        except asyncio.QueueEmpty:
            return False
        if instruction:
            self._step("System", f"[cyan]Instruction received - reorienting:[/cyan] {instruction[:200]}")
            self.history.append({"role": "user", "content": f"OPERATOR INSTRUCTION (reorient now): {instruction}"})
            self._pending_instruction = instruction
            return True
        return False

    async def _await_if_paused(self):
        while self._paused and self.active:
            await asyncio.sleep(0.15)

    async def consult_peer(self, advisor_llm: LLM, user_note: str = "") -> str:
        from config import Config as _Cfg
        if not _Cfg.A2P_ENABLED:
            return (
                "[A2P disabled] Set HADOUKING_A2P_ENABLED=1 in your .env to enable peer insight calls."
            )
        from core.a2p import advisor_system_prompt_for_pair, advisor_user_message, envelope

        exec_lbl = model_display_label(self.model)
        peer_lbl = model_display_label(advisor_llm.model)
        snap = self._format_history_for_synthesis()
        if len(snap) > 14000:
            snap = snap[:7000] + "\n\n... [truncated] ...\n\n" + snap[-7000:]
        user = advisor_user_message(
            snap,
            user_note,
            executor_label=exec_lbl,
            advisor_label=peer_lbl,
        )
        messages = [
            {
                "role": "system",
                "content": advisor_system_prompt_for_pair(exec_lbl, peer_lbl),
            },
            {"role": "user", "content": user},
        ]
        with ThinkingStatus(
            f"{self.name}: A2P — {exec_lbl} requesting insight from {peer_lbl}…"
        ):
            reply = await advisor_llm.generate(messages)
        wrapped = (
            f"\n[A2P INSIGHT from peer **{peer_lbl}** for executor **{exec_lbl}**]\n"
            f"{envelope('executor', 'advisor', 'insight', reply)}\n"
        )
        self.history.append({"role": "user", "content": wrapped})
        return reply

    def _inject_tool_context(self):
        """Injects available tools into system prompt"""
        available_tools = self.tool_validator.get_available_tools()
        tool_list = ", ".join(sorted(list(available_tools)))
        os_label = self.runtime_os
        if self.runtime_os.lower() == "linux" and self.runtime_distro:
            os_label = f"Linux ({self.runtime_distro})"
        
        context = f"\n\n## ENVIRONMENT CONTEXT\n"
        context += f"- **OS**: {os_label}\n"
        context += f"- **Workspace Isolation**: Execute commands from `{self.project_dir}`\n"
        context += f"- **Available Security Tools**: {tool_list}\n"
        context += f"- **Instruction**: You have access to these tools. Use them to execute your methodology. You are free to use standard Linux commands (grep, cat, awk, etc).\n"
        context += "- **Default Safety Policy**: Do not install/remove packages and do not delete files unless the operator explicitly authorizes it.\n"
        
        # Add Python execution instructions for ALL agents
        context += "\n## Python Script Execution\n"
        context += "You can write and execute Python scripts (```python blocks); the host runs them with `python3` and returns stdout.\n"
        context += "Use this when you need to:\n"
        context += "- Parse or aggregate tool output (JSON/XML/CSV) and extract what matters for the mission\n"
        context += "- Run **target-specific** logic: HTTP/HTTPS checks with timeouts, header/TLS inspection, batch probes **within scope**\n"
        context += "- Calculations, deduplication, small automation aligned with your agent role (recon = non-destructive; pentest agents may use heavier tooling where appropriate)\n"
        context += "- Process large datasets **by summarizing** (counts, samples, JSON lines) — never dump everything\n\n"
        context += "Format:\n"
        context += "```python\n"
        context += "# Your Python code here\n"
        context += "# IMPORTANT: Print only essential output to avoid context overflow\n"
        context += "# Use concise summaries instead of raw data dumps\n"
        context += "```\n\n"
        context += "**CRITICAL**: Your Python scripts MUST:\n"
        context += "1. Print ONLY essential results (not full datasets)\n"
        context += "2. Use summaries: 'Found 150 vulnerabilities' instead of listing all\n"
        context += "3. Output clean JSON when returning structured data\n"
        context += "4. Include error handling (try/except)\n"
        
        # Add performance/timeout guidance
        context += "\n## Command Performance & Timeouts\n"
        context += "**CRITICAL**: Commands have a 5-minute timeout. Use FAST flags to avoid timeouts:\n"
        context += "- **amass**: Use `-timeout 2` (2 min max) or avoid entirely, prefer `subfinder` instead\n"
        context += "- **nmap**: Use `-T4 --max-retries 1 -Pn` for fast scans, avoid `-p-` without reason\n"
        context += "- **nuclei**: Use `-c 50` for concurrency, `-timeout 5` for fast scanning\n"
        context += "- **dirb/gobuster**: Use `-t 50` for threads, avoid huge wordlists\n"
        context += "- **nikto**: Use `-Tuning 1-4` to limit checks\n"
        context += "\nIf a command times out, the system will suggest alternatives. PRIORITIZE SPEED.\n"
        context += "\n" + policy_summary_for_prompt()
        context += (
            "\n## Anti-command loop\n"
            "If the operator **refuses** execution or commands are **blocked**, do not repeat the same "
            "```bash block indefinitely: summarize in text and ask for guidance. The runtime stops after several "
            "rounds without real execution.\n"
        )
        self.history[0]["content"] += context

    def _inject_mcp_tools(self):
        if not self.mcp_clients:
            return

        tools_desc = "\n\n## Available MCP Tools\n"
        tools_desc += "You have access to the following external tools via Model Context Protocol (MCP). "
        tools_desc += "To use a tool, you MUST use the following format, replacing 'SERVER_NAME' and 'TOOL_NAME' with the actual names listed below:\n"
        tools_desc += "```mcp\n"
        tools_desc += "SERVER_NAME: TOOL_NAME\n"
        tools_desc += "{\n  \"arg1\": \"value1\"\n}\n"
        tools_desc += "```\n"
        tools_desc += "Example: If you have a server 'math' with tool 'add':\n"
        tools_desc += "```mcp\n"
        tools_desc += "math: add\n"
        tools_desc += "{\n  \"a\": 1,\n  \"b\": 2\n}\n"
        tools_desc += "```\n\n"
        
        # Python instructions moved to _inject_tool_context so all agents get them
        
        
        for client in self.mcp_clients:
            tools_desc += f"### Server: {client.name}\n"
            for tool in client.tools:
                tools_desc += f"- {tool['name']}: {tool.get('description', 'No description')}\n"
                if 'inputSchema' in tool:
                    schema = tool['inputSchema']
                    # Simplify schema for prompt if possible, or just dump it
                    # We'll dump the properties to be clear
                    if 'properties' in schema:
                        tools_desc += "  Arguments:\n"
                        for prop, details in schema['properties'].items():
                            prop_type = details.get('type', 'any')
                            prop_desc = details.get('description', '')
                            tools_desc += f"    * {prop} ({prop_type}): {prop_desc}\n"
                        if 'required' in schema and schema['required']:
                            tools_desc += f"  Required: {', '.join(schema['required'])}\n"
                tools_desc += "\n"
                
        self.history[0]["content"] += tools_desc

    def _inject_browser_tools(self):
        tools_desc = "\n\n## Available Browser Tools\n"
        tools_desc += "You have access to a real browser. When you navigate, you will receive an 'Interactive Map' of elements (buttons, links, inputs).\n"
        
        if self.browser_intelligence:
            tools_desc += "**VISION MODE ENABLED**: After each navigation, you will also receive a SCREENSHOT of the page. Analyze it visually to understand the layout, identify interactive elements, and plan your next actions.\n"
        
        tools_desc += "Each element has an index, tag, text, and a suggested selector.\n"
        tools_desc += "To interact, prefer using the 'selector' provided in the map.\n"
        tools_desc += "Format:\n"
        tools_desc += "```browser\n"
        tools_desc += "tool_name\n"
        tools_desc += "{\n  \"arg1\": \"value1\"\n}\n"
        tools_desc += "```\n"
        tools_desc += "Tools:\n"
        tools_desc += "- navigate: Go to a URL. Returns Interactive Map. Args: url\n"
        tools_desc += "- click: Click an element. Args: selector\n"
        tools_desc += "- type: Type text. Args: selector, text\n"
        tools_desc += "- screenshot: Save screenshot. Args: path (optional)\n"
        tools_desc += "- get_content: Get page text. No args.\n"
        tools_desc += "- get_interactive_elements: Refresh the Interactive Map. No args.\n"
        
        self.history[0]["content"] += tools_desc

    async def process_message(self, message):
        """
        Processes a user message and starts the autonomous loop.
        """
        # Guardrail Check Input
        is_safe, reason = Guardrails.check_input(message)
        if not is_safe:
            self._step("Observation", f"[bold red]Blocked Input:[/bold red] {reason}")
            return "Input blocked by guardrails."

        # Dynamic Context Injection
        try:
            keywords = self.context_loader.extract_keywords(message)
            contexts = self.context_loader.get_relevant_context(self.name, keywords)
            
            if contexts:
                context_content = "\n\n".join(contexts)
                
                # Add visual separator and inject
                injection = f"\n\n[SYSTEM: METHODOLOGY CONTEXT LOADED]\n{context_content}\n[END CONTEXT]\n"
                message += injection
                
                # Log to UI
                self._step("System", f"Loaded methodology context for: {', '.join(keywords)}")
                self.context_injection_count += 1
                self.context_docs_loaded += len(contexts)
        except Exception as e:
            self._step("Error", f"Failed to load context: {e}")

        self.history.append({"role": "user", "content": message})
        await self.autonomous_loop()
        return "Loop finished."

    async def autonomous_loop(self, target_ip=None):
        """
        The core "Think-Execute-Observe" loop.
        """
        consecutive_no_commands = 0  # Track loops without commands
        max_no_command_loops = 3  # Stop after 3 consecutive loops with no commands
        stuck_no_exec_rounds = 0  # Rounds with bash/MCP/... but zero executions (refused/blocked)
        agent_turn = 0

        if target_ip:
            self.report_generator.set_target(target_ip)

        while self.active:
            await self._await_if_paused()

            # Preemption checkpoint: check for queued operator instructions
            if await self._drain_instruction_queue():
                continue

            # Check Action Limit
            if self.action_count >= self.limit:
                self._step(
                    "System",
                    f"[yellow]Action limit ({self.limit}) reached. Stopping and summarizing…[/yellow]",
                )
                await self.stop()
                break

            agent_turn += 1
            if agent_turn > Config.HADOUKING_MAX_AGENT_TURNS:
                self._step(
                    "System",
                    f"[yellow]Turn limit reached ({Config.HADOUKING_MAX_AGENT_TURNS}). "
                    "Stopping to avoid infinite loop. Adjust HADOUKING_MAX_AGENT_TURNS if you need more.[/yellow]",
                )
                await self.stop()
                break

            actions_at_turn_start = self.action_count

            # 1. Think (Generate response)
            await self._monitor_context()
            with ThinkingStatus(f"{self.name}: main model generating response…"):
                response = None
                llm_timeout = Config.HADOUKING_LLM_TIMEOUT_SEC
                max_retries = max(0, int(Config.HADOUKING_LLM_RETRIES))
                for attempt in range(max_retries + 1):
                    try:
                        response = await asyncio.wait_for(
                            self.llm.generate(self.history),
                            timeout=llm_timeout,
                        )
                        break
                    except asyncio.TimeoutError:
                        if attempt < max_retries:
                            self._step(
                                "System",
                                f"[yellow]LLM timeout ({llm_timeout:.0f}s). Retrying {attempt + 1}/{max_retries}…[/yellow]",
                            )
                            continue
                        self._step(
                            "Error",
                            f"[red]LLM request timed out ({llm_timeout:.0f}s) after {max_retries + 1} attempt(s).[/red]",
                        )
                        response = None
                        break
                    except Exception as e:
                        self._step("Error", f"[red]LLM error: {str(e)}[/red]")
                        response = None
                        break
            if response is None:
                break
            
            # Check if response is valid
            if not response or response.startswith("Error"):
                self._step("Error", f"[red]Invalid LLM response: {response}[/red]")
                break
            
            self.history.append({"role": "assistant", "content": response})
            
            # 2. Check for commands (Bash, Python, MCP, and Browser)
            bash_commands = self._extract_bash_commands(response)
            python_scripts = self._extract_python_code(response)
            mcp_commands = self._extract_mcp_commands(response)
            browser_commands = self._extract_browser_commands(response)
            
            if not bash_commands and not python_scripts and not mcp_commands and not browser_commands:
                consecutive_no_commands += 1
                self._step("Output", response)
                
                if consecutive_no_commands >= max_no_command_loops:
                    self._step(
                        "System",
                        f"[yellow]{max_no_command_loops} consecutive loops without executable commands. Stopping.[/yellow]",
                    )
                    break
                
                # Continue loop to give agent another chance
                continue
            
            # Reset counter if commands were found
            consecutive_no_commands = 0
            
            # If commands found, we skip showing the "thought process" text in Silent Mode
            # to make it feel faster and less verbose.
            # self._step("Output", response) # Commented out for Silent Mode
            
            # 3. Execute Commands
            
            # Execute Bash Commands
            for cmd in bash_commands:
                if not self.active: break
                
                # Loop Detection
                if self._detect_loop(cmd):
                    self.loop_count += 1
                    warning = f"SYSTEM ALERT: Loop detected. You have executed '{cmd}' 3 times in a row. STOP and try a different approach."
                    self._step("System", f"[bold red]Loop detected:[/bold red] {cmd}")
                    self.history.append({"role": "user", "content": warning})
                    
                    if self.loop_count >= 3: # 3 warnings = 9 repetitions total (approx)
                         self._step(
                             "System",
                             "[bold red]Critical loop: stopping agent (avoid exhaustion).[/bold red]",
                         )
                         await self.stop()
                         break
                    continue
                else:
                    self.loop_count = 0 # Reset if new command
                    self.command_history.append(cmd)
                
                # Guardrail Check Command
                if (not self.allow_installs) and re.search(
                    r"(?:^|\s)(?:apt|apt-get|dpkg|dnf|yum|pacman|pip|pip3|npm|cargo)\s+"
                    r"(?:install|remove|uninstall|upgrade)\b",
                    cmd,
                    re.IGNORECASE,
                ):
                    self._step(
                        "Observation",
                        "[bold red]Blocked by default policy:[/bold red] package installation/removal is disabled.",
                    )
                    self.history.append(
                        {
                            "role": "user",
                            "content": "Policy blocked command: package install/remove requires explicit operator approval.",
                        }
                    )
                    continue

                if (not self.allow_deletes) and re.search(
                    r"(?:^|\s)(?:rm|rmdir|shred)\b",
                    cmd,
                    re.IGNORECASE,
                ):
                    self._step(
                        "Observation",
                        "[bold red]Blocked by default policy:[/bold red] destructive delete commands are disabled.",
                    )
                    self.history.append(
                        {
                            "role": "user",
                            "content": "Policy blocked command: delete operations require explicit operator approval.",
                        }
                    )
                    continue

                is_safe, reason = Guardrails.check_command(cmd)
                
                if not is_safe:
                    self._step("Observation", f"[bold red]Command blocked (guardrails):[/bold red] {reason}")
                    self.history.append({"role": "user", "content": f"Command blocked by guardrails: {reason}"})
                    continue

                tier, tier_note = classify_command(cmd)
                blocked, block_reason = is_blocked(tier)
                if blocked:
                    self._step("Observation", f"[bold red]Blocked by policy:[/bold red] {block_reason}")
                    self.history.append({"role": "user", "content": f"Policy blocked command: {block_reason}"})
                    continue

                # Human confirmation (tiered mode ≈ Claude/Codex: only network/mutation/priv)
                if needs_user_confirmation(tier, self._is_auto_approve_active()):
                    if not await self._safety_check(
                        cmd,
                        tier_label=f"{tier.name} — {tier_note}",
                        tier_name=tier.name,
                        approval_key=self._approval_key_for_bash(cmd),
                    ):
                        self._step("Observation", f"Command denied by user: {cmd}")
                        self.history.append({"role": "user", "content": f"User denied execution of: {cmd}"})
                        continue

                self._step("Executing", cmd)
                with ThinkingStatus(f"{self.name}: executing command…"):
                    output = await execute_command(cmd, cwd=self.project_dir)
                output = maybe_compress_for_llm(output)
                
                self.action_count += 1
                
                # 4. Observe (Add output to history)
                observation = f"Command: {cmd}\nOutput:\n{output}"
                
                if self.output_analyzer:
                    analysis = await self.output_analyzer.analyze(cmd, output)
                    if analysis.get("relevant"):
                        summary = analysis.get("summary", "No summary provided.")
                        observation = f"Command: {cmd}\nOutput Analysis (Summary):\n{summary}"
                        if analysis.get("new_tasks"):
                            observation += f"\nSuggested Tasks: {', '.join(analysis['new_tasks'])}"
                        
                        # Add finding to report generator
                        self.report_generator.add_finding(
                            title=f"Finding from {cmd}",
                            severity="Info",
                            description=summary,
                            remediation="Review output."
                        )
                    else:
                        observation = f"Command: {cmd}\nOutput Analysis: Output deemed irrelevant/noise."
                
                # In Silent Mode, we might want to hide the raw output if it's huge, 
                # but for now we keep it to verify execution.
                self._step("Observation", output)
                self.history.append({"role": "user", "content": observation})

            # Preemption checkpoint after bash execution
            if await self._drain_instruction_queue():
                continue

            # Execute Python Scripts
            for script in python_scripts:
                if not self.active: break
                
                # Loop Detection
                script_hash = str(hash(script))  # Use hash to detect same script
                if self._detect_loop(script_hash):
                    self.loop_count += 1
                    warning = f"SYSTEM ALERT: Loop detected. You have executed the same Python script 3 times. STOP and try a different approach."
                    self._step("System", f"[bold red]Loop Detected: Same Python script[/bold red]")
                    self.history.append({"role": "user", "content": warning})
                    
                    if self.loop_count >= 3:
                        self._step("System", "[bold red]Critical Loop detected. Stopping agent.[/bold red]")
                        await self.stop()
                        break
                    continue
                else:
                    self.loop_count = 0
                    self.command_history.append(script_hash)
                
                # Save script to temp file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(script)
                    script_path = f.name
                
                try:
                    ptier, pnote = classify_python_script(script)
                    blocked_py, block_py = is_blocked(ptier)
                    if blocked_py:
                        self._step(
                            "Observation",
                            f"[bold red]Blocked by policy:[/bold red] {block_py}",
                        )
                        self.history.append(
                            {"role": "user", "content": f"Policy blocked Python script: {block_py}"}
                        )
                        continue
                    if needs_user_confirmation(ptier, self._is_auto_approve_active()):
                        prev = script[:3500] + ("\n\n... [script truncated] ...\n\n" if len(script) > 3500 else "")
                        disp = f"python3 <temporary script, {len(script)} chars>\n\n{prev}"
                        if not await self._safety_check(
                            disp,
                            tier_label=f"{ptier.name} — {pnote}",
                            tier_name=ptier.name,
                            approval_key=self._approval_key_for_python(script),
                        ):
                            self._step(
                                "Observation",
                                "Python script denied by user.",
                            )
                            self.history.append(
                                {"role": "user", "content": "User denied execution of Python script"}
                            )
                            continue

                    self._step("Executing", f"Python script ({len(script)} chars)")
                    with ThinkingStatus(f"{self.name}: executing Python script…"):
                        # Execute with python3
                        output = await execute_command(
                            f"python3 {script_path}",
                            cwd=self.project_dir,
                        )
                    output = maybe_compress_for_llm(output)
                    
                    self.action_count += 1
                    
                    # Observe
                    observation = f"Python Script Executed:\n```python\n{script[:500]}{'...' if len(script) > 500 else ''}\n```\nOutput:\n{output}"
                    
                    if self.output_analyzer:
                        analysis = await self.output_analyzer.analyze(f"Python script", output)
                        if analysis.get("relevant"):
                            summary = analysis.get("summary", "No summary provided.")
                            observation = f"Python Script Output (Summary):\n{summary}"
                            if analysis.get("new_tasks"):
                                observation += f"\nSuggested Tasks: {', '.join(analysis['new_tasks'])}"
                        else:
                            observation = f"Python Script Output: Deemed irrelevant/noise."
                    
                    self._step("Observation", output)
                    self.history.append({"role": "user", "content": observation})
                    
                finally:
                    # Clean up temp file
                    try:
                        os.unlink(script_path)
                    except Exception:
                        pass

            # Preemption checkpoint after Python execution
            if await self._drain_instruction_queue():
                continue

            # Execute MCP Commands
            for server_name, tool_name, args in mcp_commands:
                if not self.active: break
                
                self._step("Executing MCP", f"{server_name}:{tool_name}")
                
                # Find client
                client = next((c for c in self.mcp_clients if c.name == server_name), None)
                if not client:
                    error_msg = f"MCP Server '{server_name}' not found."
                    self._step("Error", error_msg)
                    self.history.append({"role": "user", "content": f"MCP Error: {error_msg}"})
                    continue
                    
                with ThinkingStatus(f"{self.name}: MCP · {tool_name}…"):
                    try:
                        result = await client.call_tool(tool_name, args)
                        self.action_count += 1
                        # Format result
                        content = result.get("content", [])
                        text_content = ""
                        for item in content:
                            if item.get("type") == "text":
                                text_content += item.get("text", "")
                        
                        if not text_content.strip():
                            text_content = "No output from tool."

                        text_content = maybe_compress_for_llm(text_content)
                        observation = f"MCP Tool: {server_name}:{tool_name}\nResult:\n{text_content}"
                        
                        if self.output_analyzer:
                            analysis = await self.output_analyzer.analyze(f"MCP Tool: {server_name}:{tool_name}", text_content)
                            if analysis.get("relevant"):
                                summary = analysis.get("summary", "No summary provided.")
                                observation = f"MCP Tool: {server_name}:{tool_name}\nResult Analysis (Summary):\n{summary}"
                                if analysis.get("new_tasks"):
                                    observation += f"\nSuggested Tasks: {', '.join(analysis['new_tasks'])}"
                            else:
                                observation = f"MCP Tool: {server_name}:{tool_name}\nResult Analysis: Output deemed irrelevant/noise."

                        self._step("Observation", text_content[:500] + "..." if len(text_content) > 500 else text_content)
                        self.history.append({"role": "user", "content": observation})
                        
                    except Exception as e:
                        error_msg = f"Tool execution failed: {str(e)}"
                        self._step("Error", error_msg)
                        self.history.append({"role": "user", "content": f"MCP Error: {error_msg}"})

            # Preemption checkpoint after MCP execution
            if await self._drain_instruction_queue():
                continue

            # Execute Browser Commands
            if self.use_browser and self.browser_manager:
                for tool_name, args in browser_commands:
                    if not self.active: break
                    
                    self._step("Executing Browser", f"{tool_name}")
                    
                    with ThinkingStatus(f"{self.name}: browser · {tool_name}…"):
                        try:
                            result = ""
                            screenshot_base64 = None
                            
                            if tool_name == "navigate":
                                result = await self.browser_manager.navigate(args.get("url"))
                                
                                # If browser intelligence is enabled, capture screenshot
                                if self.browser_intelligence:
                                    screenshot_base64 = await self.browser_manager.screenshot_base64()
                                    if screenshot_base64:
                                        self._step("Vision", "Analyzing screenshot…")
                                        
                            elif tool_name == "click":
                                result = await self.browser_manager.click(args.get("selector"))
                            elif tool_name == "type":
                                result = await self.browser_manager.type(args.get("selector"), args.get("text"))
                            elif tool_name == "screenshot":
                                result = await self.browser_manager.screenshot(args.get("path", "screenshot.png"))
                            elif tool_name == "get_content":
                                result = await self.browser_manager.get_content()
                            elif tool_name == "get_interactive_elements":
                                result = await self.browser_manager.get_interactive_elements()
                            else:
                                result = f"Unknown browser tool: {tool_name}"
                            
                            self.action_count += 1
                            if isinstance(result, str):
                                result = maybe_compress_for_llm(result)
                            observation = f"Browser Tool: {tool_name}\nResult:\n{result}"
                            
                            # If we have a screenshot, add vision analysis
                            if screenshot_base64:
                                observation += "\n\n[Screenshot captured for visual analysis]"
                            
                            self._step("Observation", result[:500] + "..." if len(result) > 500 else result)
                            self.history.append({"role": "user", "content": observation})
                            
                            # If vision mode, immediately ask LLM to analyze the screenshot
                            if screenshot_base64:
                                with ThinkingStatus(f"{self.name}: vision · analyzing image…"):
                                    vision_response = await self.llm.generate(self.history, image_base64=screenshot_base64)
                                self.history.append({"role": "assistant", "content": vision_response})
                                self._step("Vision Analysis", vision_response)
                            
                        except Exception as e:
                            error_msg = f"Browser tool failed: {str(e)}"
                            self._step("Error", error_msg)
                            self.history.append({"role": "user", "content": f"Browser Error: {error_msg}"})

            # Preemption checkpoint after Browser execution
            if await self._drain_instruction_queue():
                continue

            # Context stats display after each think/execute/observe cycle
            self._update_context_display()

            # End of turn: there were tool blocks in the response but nothing executed (refused/blocked/all errors)
            had_tool_blocks = bool(
                bash_commands or python_scripts or mcp_commands or browser_commands
            )
            if had_tool_blocks and self.action_count == actions_at_turn_start:
                stuck_no_exec_rounds += 1
                self.history.append(
                    {
                        "role": "user",
                        "content": (
                            "SYSTEM (Hadouking): This response contained execution blocks (bash/python/MCP/browser) "
                            "but **no** command was executed in this round (refused, blocked by policy/guardrails "
                            "or failed). Do not repeat the same suggestion in a loop. Respond in **plain text**: "
                            "status summary, risks and **manual** next steps for the operator. "
                            "Only use ```bash blocks again when the operator confirms or uses --auto-approve. "
                            "If the objective is complete, provide a final conclusion with no new commands."
                        ),
                    }
                )
                if stuck_no_exec_rounds >= Config.HADOUKING_MAX_STUCK_COMMAND_ROUNDS:
                    self._step(
                        "System",
                        f"[bold red]Stopped:[/bold red] {Config.HADOUKING_MAX_STUCK_COMMAND_ROUNDS} consecutive rounds "
                        "with command suggestions but **zero** executions (avoids infinite confirmation loop). "
                        "Use `--auto-approve` or relax policy; or increase HADOUKING_MAX_STUCK_COMMAND_ROUNDS.",
                    )
                    await self.stop()
                    break
            elif self.action_count > actions_at_turn_start:
                stuck_no_exec_rounds = 0

    def _detect_loop(self, command: str) -> bool:
        """
        Checks if the command has been executed consecutively multiple times.
        Returns True if a loop is detected (3+ repetitions).
        """
        if len(self.command_history) < 2:
            return False
            
        # Check last 2 commands
        if self.command_history[-1] == command and self.command_history[-2] == command:
            return True
            
        return False

    def _extract_bash_commands(self, text):
        commands = re.findall(r"```bash\s+(.+?)\s+```", text, re.DOTALL)
        normalized = []
        seen = set()

        def _add(cmd: str):
            c = (cmd or "").strip()
            if not c:
                return
            if c in seen:
                return
            seen.add(c)
            normalized.append(c)

        for cmd in commands:
            _add(cmd)

        # Optional fallback extraction when model forgets fenced ```bash``` blocks.
        # Disabled by default because inline text is easier to poison via prompt injection.
        if not normalized and Config.HADOUKING_ALLOW_INLINE_BASH_FALLBACK:
            inline_cmds = re.findall(
                r"`((?:curl|wget|httpx|nmap|nikto|python3|bash|nc|dig|host)\b[^`\n]*)`",
                text,
                re.IGNORECASE,
            )
            for cmd in inline_cmds:
                _add(cmd)

            for line in text.splitlines():
                s = line.strip()
                if not s:
                    continue
                s = re.sub(r"^[-*]\s*", "", s)
                s = re.sub(r"^\d+[.)]\s*", "", s)
                if re.match(
                    r"^(curl|wget|httpx|nmap|nikto|python3|bash|nc|dig|host)\b",
                    s,
                    re.IGNORECASE,
                ):
                    _add(s)

        return normalized
    
    def _extract_python_code(self, text):
        """Extract Python code blocks from LLM response."""
        return re.findall(r"```python\s+(.+?)\s+```", text, re.DOTALL)

    def _extract_mcp_commands(self, text):
        """
        Extracts MCP tool calls in the format:
        ```mcp
        server_name: tool_name
        {json_args}
        ```
        """
        commands = []
        pattern = r"```mcp\s+(.+?):\s+(.+?)\s+(\{.*?\})\s+```"
        matches = re.findall(pattern, text, re.DOTALL)
        for server, tool, args_str in matches:
            try:
                args = json.loads(args_str)
                commands.append((server.strip(), tool.strip(), args))
            except json.JSONDecodeError:
                pass
        return commands

    def _extract_browser_commands(self, text):
        """
        Extracts Browser tool calls in the format:
        ```browser
        tool_name
        {json_args}
        ```
        """
        commands = []
        pattern = r"```browser\s+(.+?)\s+(\{.*?\})\s+```"
        matches = re.findall(pattern, text, re.DOTALL)
        for tool, args_str in matches:
            try:
                args = json.loads(args_str)
                commands.append((tool.strip(), args))
            except json.JSONDecodeError:
                pass
        
        # Handle no-arg commands (like get_content) if they are formatted differently?
        # For now, assume they pass empty json {}
        
        return commands

    def _is_auto_approve_active(self) -> bool:
        return bool(self.auto_approve or self._session_auto_approve)

    def _scoped_approval_key(self, approval_key: str) -> str:
        return f"{self._approval_session_id}|{approval_key}"

    def _approval_key_for_bash(self, command: str) -> str:
        return f"bash::{(command or '').strip()}"

    def _approval_key_for_python(self, script: str) -> str:
        digest = hashlib.sha256((script or "").encode("utf-8")).hexdigest()
        return f"python::{digest}"

    def get_approval_cache_state(self) -> Dict[str, Any]:
        """Session-local approval cache snapshot for optional UI/debug hooks."""
        summary = self.approval_state.get_summary()
        return {
            "session_id": summary["session_id"],
            "exact_approvals": summary["session_commands"],
            "session_tiers": summary["session_tiers"],
            "tier_approvals": len(summary["session_tiers"]),
            "session_always": summary["session_always"],
            "cli_auto_approve": bool(self.auto_approve),
            "persistent_tiers": summary["persistent_tiers"],
            "persistent_commands": summary["persistent_commands"],
        }

    async def _safety_check(
        self,
        command,
        tier_label: str = "",
        tier_name: str = "",
        approval_key: str = "",
    ):
        """
        Asks user for approval before executing.
        Uses ApprovalState for session + persistent approval caching.
        """
        if self._is_auto_approve_active():
            return True

        exact_key = approval_key or command
        scoped_exact_key = self._scoped_approval_key(exact_key)

        mode = exec_mode()
        force_prompt = mode in ("always_confirm", "all", "legacy")

        # Check approval_state (covers session + persistent tiers/commands)
        if (not force_prompt) and self.approval_state.check_approved(scoped_exact_key, tier_name):
            return True

        loop = asyncio.get_running_loop()
        decision = await loop.run_in_executor(
            None,
            lambda: ask_command_approval(
                command,
                tier_label=tier_label,
                approval_cache=self.get_approval_cache_state(),
            ),
        )
        if decision is True:
            return True
        if decision is False:
            return False
        if decision == "always":
            self._session_auto_approve = True
            self.approval_state.record_approval("always")
            self._step(
                "System",
                "[green]Approval mode updated:[/green] always approve enabled for this agent session.",
            )
            return True
        if decision == "scope":
            if tier_name:
                self.approval_state.record_approval("scope", tier_name=tier_name)
                self._step(
                    "System",
                    f"[green]Approval scope updated:[/green] risk tier '{tier_name}' approved for this agent session.",
                )
            return True
        if decision == "persist_scope":
            if tier_name:
                self.approval_state.record_approval("scope", tier_name=tier_name, persist=True)
                self._step(
                    "System",
                    f"[green]Approval scope updated (persisted):[/green] risk tier '{tier_name}' approved across restarts.",
                )
            return True
        if decision == "command":
            self.approval_state.record_approval("command", approval_key=scoped_exact_key)
            self._step(
                "System",
                "[green]Approval scope updated:[/green] exact command approved for this agent session.",
            )
            return True
        if decision == "persist_command":
            self.approval_state.record_approval("command", approval_key=scoped_exact_key, persist=True)
            self._step(
                "System",
                "[green]Approval scope updated (persisted):[/green] exact command approved across restarts.",
            )
            return True
        if decision == "once":
            return True
        return False

    async def stop(self):
        """
        Stops the agent and generates a report.
        """
        if self._stopped:
            return self.report_generator.executive_summary or "Agent already stopped."

        self._stopped = True
        self.active = False
        self._step("System", "Stopping agent…")

        # Cleanup browser if active
        if self.browser_manager and self.browser_manager.active:
            try:
                await self.browser_manager.stop()
            except Exception:
                pass

        # Generate LLM synthesis of all findings and discoveries
        from rich.status import Status
        from utils.ui import console

        if self.action_count == 0:
            synthesis = (
                "No validated security findings.\n\n"
                "- No command/tool execution was completed in this run.\n"
                "- Therefore, there is no runtime evidence to confirm vulnerabilities.\n"
                "- Review prompt constraints and rerun with explicit executable steps.\n"
                "- Treat any prior model-only claims as hypotheses, not findings."
            )
        else:
            with Status(f"[bold green]{self.name}: synthesizing conclusions…", console=console):
                synthesis_prompt = [
                    {
                        "role": "system",
                        "content": (
                            "You are a security analyst creating an evidence-based executive summary. "
                            "Do not invent vulnerabilities. Only report findings backed by explicit command/tool outputs. "
                            "If evidence is insufficient, state that clearly."
                        ),
                    },
                    {"role": "user", "content": f"""Based on the following conversation history, provide a comprehensive executive summary of the security assessment.

Focus on:
1. **Vulnerabilities Found**: List only confirmed vulnerabilities with severity
2. **Security Findings**: Important evidence-backed discoveries
3. **Attack Surface**: Exposed services, technologies, and potential entry points validated in output
4. **Recommendations**: Top 3-5 critical actions grounded in observed evidence

Be concise but comprehensive. Use bullet points.

Conversation History:
{self._format_history_for_synthesis()}

Provide the executive summary now:"""}
                ]

                try:
                    synthesis = await self.llm.generate(synthesis_prompt)
                except Exception as e:
                    synthesis = f"Error generating synthesis: {e}\n\nPlease review the full report for details."
        
        # Use synthesis as executive summary
        self.report_generator.set_executive_summary(synthesis)
        
        # Save Report
        report_path = self.report_generator.save_report(output_dir=self.project_dir)
        self._step("Report", f"Report saved to: {report_path}")
        
        # Display summary in terminal
        from rich.panel import Panel
        from rich.markdown import Markdown
        
        # Create visual summary
        summary_md = f"## 🎯 Executive Summary\n\n{synthesis}\n\n"

        # Add findings count if any
        if self.report_generator.findings:
            summary_md += f"---\n\n### 📊 Findings: {len(self.report_generator.findings)}\n"

        console.print(
            Panel(
                Markdown(summary_md),
                title=f"[bold green]{self.name} — assessment summary[/bold green]",
                border_style="green",
                expand=False,
            )
        )
        
        return synthesis
    
    def _format_history_for_synthesis(self) -> str:
        """Format conversation history for LLM synthesis, prioritizing findings and tool outputs."""
        formatted = []
        total_chars = 0
        max_total_chars = 300000  # ~75k tokens - maximize context for comprehensive analysis
        
        # Prioritize messages with tool outputs (commands and observations)
        important_messages = []
        other_messages = []
        
        for msg in self.history[1:]:  # Skip system prompt
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            # Check if this is a tool output (contains command results)
            is_important = (
                "Command:" in content or 
                "Output:" in content or 
                "MCP Tool:" in content or
                "vulnerability" in content.lower() or
                "found" in content.lower() or
                "discovered" in content.lower() or
                role == "user"  # User messages are observations from tools
            )
            
            if is_important:
                important_messages.append((role, content))
            else:
                other_messages.append((role, content))
        
        # First, add all important messages (with smart truncation)
        for role, content in important_messages:
            # For important messages, keep more content to preserve scan results
            if len(content) > 15000:
                # Try to keep beginning and end (often has summary)
                content = content[:7500] + "\n\n... [middle truncated] ...\n\n" + content[-7500:]
            
            msg_text = f"[{role.upper()}]: {content}"
            
            if total_chars + len(msg_text) > max_total_chars:
                break
                
            formatted.append(msg_text)
            total_chars += len(msg_text)
        
        # If we have room, add some recent other messages for context
        for role, content in other_messages[-10:]:  # Last 10 non-important messages
            if total_chars >= max_total_chars:
                break
                
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            
            msg_text = f"[{role.upper()}]: {content}"
            
            if total_chars + len(msg_text) > max_total_chars:
                break
                
            formatted.append(msg_text)
            total_chars += len(msg_text)
        
        result = "\n\n".join(formatted)
        return result if result else "No significant findings in history."

    async def _monitor_context(self):
        """
        Checks current token usage and triggers compaction if threshold is reached.
        """
        total_tokens = count_tokens(self.history, self.llm.model)
        if total_tokens > self.max_context_tokens * self.compaction_threshold:
            self._step(
                "Context",
                f"[yellow]Context limit approaching ({total_tokens}/{self.max_context_tokens}). Compacting…[/yellow]",
            )
            await self.compact_history()

    def _get_context_stats(self) -> Dict[str, int]:
        """Return context usage statistics for the current agent session."""
        total_messages = len(self.history)
        try:
            estimated_tokens = count_tokens(self.history, self.llm.model)
        except Exception:
            estimated_tokens = sum(
                len(msg.get("content", "")) // 4 for msg in self.history
            )
        return {
            "total_messages": total_messages,
            "estimated_tokens": estimated_tokens,
        }

    def _update_context_display(self):
        """Print a one-line context status after each think/execute/observe cycle."""
        stats = self._get_context_stats()
        self._step(
            "Context",
            f"~{stats['estimated_tokens']} tokens across {stats['total_messages']} messages",
        )

    async def compact_history(self, keep_last=5):
        """
        Summarizes the conversation history to save tokens.
        Aggressively truncates if necessary.
        """
        # 1. Identify summarizable history (keep system prompt + last N messages)
        if len(self.history) <= keep_last + 1:
            # Even if short, check for massive messages in the last few
            self._truncate_recent_history()
            return

        messages_to_summarize = self.history[1:-keep_last] # Skip system prompt (0) and keep last N
        messages_to_keep = self.history[-keep_last:]
        
        # Truncate messages_to_keep if they are huge
        for msg in messages_to_keep:
            if len(msg["content"]) > 20000:
                msg["content"] = msg["content"][:20000] + "\n... [TRUNCATED DUE TO SIZE] ..."
        
        # 2. Generate Summary
        summary_prompt = """You are a Technical Findings Summarizer.
Your goal is to extract HARD DATA and ACTIONABLE FINDINGS from the session.
Do NOT write a narrative. Do NOT explain "The session began with...".
Use bullet points.

STRUCTURE:
1. **Assets Discovered**:
   - List subdomains, IPs, open ports, services, technologies.
   - Be specific (e.g., "Webmin on port 10000", "WordPress 5.8").

2. **Vulnerabilities & Issues**:
   - For EACH vulnerability, you MUST include:
     * Full URL with complete payload (e.g., "https://example.com/search?q=<script>alert(1)</script>")
     * Vulnerability type (e.g., "XSS", "SQLi", "SSRF")
     * Severity if known
   - List any misconfigurations.
   - If none, state "No direct vulnerabilities identified yet."

3. **Execution Errors**:
   - Briefly list tools that failed or had syntax errors (so the user knows to fix them).

4. **Next Steps**:
   - What should be done next based on these findings?
   - Be specific (e.g., "Brute force Webmin login", "Scan new subdomains").

Keep it CONCISE.
This session is being continued from a previous conversation that ran out of context. The conversation is summarized below:"""
        
        # We use a temporary history for the summarization task
        summary_input = [{"role": "system", "content": summary_prompt}]
        
        # Format the conversation history
        conversation_text = self._format_history_for_summary(messages_to_summarize)
        
        # Safe limit for summarizer input (approx 50k tokens ~ 200k chars)
        if len(conversation_text) > 200000:
             # Keep the END of the conversation as it's most relevant for context continuity
             conversation_text = "... [EARLY HISTORY TRUNCATED] ...\n" + conversation_text[-200000:]
        
        summary_input.append({"role": "user", "content": conversation_text})
        
        with ThinkingStatus(f"{self.name}: summarizing history…"):
            # Use the same LLM for summarization
            try:
                summary = await self.llm.generate(summary_input)
            except Exception as e:
                summary = f"Error generating summary: {e}. Proceeding with truncated history."

        # 3. Update History
        # Create a new system prompt with the summary appended
        new_system_prompt_content = self.system_prompt + f"\n\n[PREVIOUS CONVERSATION SUMMARY]:\n{summary}"
        
        # Reconstruct history: Updated System Prompt + Kept Messages
        self.history = [{"role": "system", "content": new_system_prompt_content}] + messages_to_keep
        
        new_token_count = count_tokens(self.history, self.llm.model)
        self._step(
            "Context",
            f"[green]History compacted. Tokens ~{new_token_count}[/green]",
        )

    def _truncate_recent_history(self):
        """
        Truncates recent messages if they are too large, even if we can't compact yet.
        """
        for msg in self.history:
            if msg["role"] != "system" and len(msg["content"]) > 20000:
                 msg["content"] = msg["content"][:20000] + "\n... [TRUNCATED DUE TO SIZE] ..."

    def _format_history_for_summary(self, history):
        """
        Format message history for summarization.
        Formats messages for the context summary.
        """
        formatted_parts = []
        for msg in history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if not content:
                continue
                
            if role == "user":
                # Check if it's an observation (tool output)
                if content.startswith("Command:") and "\nOutput:\n" in content:
                    formatted_parts.append(f"TOOL OUTPUT: {content}")
                elif content.startswith("MCP Tool:") and "\nResult:\n" in content:
                    formatted_parts.append(f"MCP OUTPUT: {content}")
                else:
                    formatted_parts.append(f"USER: {content}")
            elif role == "assistant":
                formatted_parts.append(f"ASSISTANT: {content}")
            elif role == "system":
                # Skip system prompt in the formatted conversation flow for summary
                continue
                
        return "\n\n".join(formatted_parts)

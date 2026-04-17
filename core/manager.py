import asyncio
from pathlib import Path
from .agent import Agent
from .project_manager import ProjectManager
from utils.ui import print_agent_step

class AgentManager:
    def __init__(self, shared_project_dir=None):
        self.agents = {}
        # Create shared project for multi-agent sessions
        self.project_manager = ProjectManager()
        if shared_project_dir:
            self.shared_project_dir = shared_project_dir
            Path(self.shared_project_dir).mkdir(parents=True, exist_ok=True)
        else:
            self.shared_project_dir = self.project_manager.create_new_project()
        print_agent_step(
            "AgentManager",
            "Project",
            f"Shared project created at: {self.shared_project_dir}",
        )

    def add_agent(
        self,
        name,
        model,
        system_prompt,
        mcp_clients=None,
        output_analyzer=None,
        auto_approve=False,
        limit=10,
        use_browser=False,
        headless=True,
        browser_intelligence=False,
        auth_manager=None,
        allow_installs=False,
        allow_deletes=False,
        runtime_os=None,
        runtime_distro=None,
    ):
        if name in self.agents:
            return f"Agent '{name}' already exists. Use '--name <new_name>' to add another instance."
        # Pass shared project directory to all agents
        self.agents[name] = Agent(
            name,
            model,
            system_prompt,
            mcp_clients=mcp_clients,
            output_analyzer=output_analyzer,
            auto_approve=auto_approve,
            limit=limit,
            use_browser=use_browser,
            headless=headless,
            browser_intelligence=browser_intelligence,
            project_dir=self.shared_project_dir,
            auth_manager=auth_manager,
            allow_installs=allow_installs,
            allow_deletes=allow_deletes,
            runtime_os=runtime_os,
            runtime_distro=runtime_distro,
        )
        return (
            f"Agent {name} added (model: {model}, auto-approve: {auto_approve}, "
            f"MCPs: {len(mcp_clients or [])}, limit: {limit}, browser: {use_browser}, "
            f"headless: {headless}, vision: {browser_intelligence})."
        )

    def remove_agent(self, name):
        if name in self.agents:
            del self.agents[name]
            return f"Agent {name} removed."
        return f"Agent {name} not found."

    def list_agents(self):
        return list(self.agents.keys())

    async def broadcast(self, message):
        """
        Sends a message to all active agents and runs them in PARALLEL.
        Each agent runs one iteration at a time, truly concurrent.
        """
        for name, agent in self.agents.items():
            # Guardrail Check Input
            from .guardrails import Guardrails
            is_safe, reason = Guardrails.check_input(message)
            if not is_safe:
                print_agent_step(
                    name,
                    "Observation",
                    f"[bold red]Input blocked (guardrails):[/bold red] {reason}",
                    model=agent.model,
                )
                continue

            # Dynamic Context Injection
            try:
                keywords = agent.context_loader.extract_keywords(message)
                contexts = agent.context_loader.get_relevant_context(name, keywords)

                if contexts:
                    context_content = "\n\n".join(contexts)
                    injection = f"\n\n[SYSTEM: METHODOLOGY CONTEXT LOADED]\n{context_content}\n[END CONTEXT]\n"
                    message_with_context = message + injection
                    print_agent_step(
                        name,
                        "System",
                        f"Methodology context loaded: {', '.join(keywords)}",
                        model=agent.model,
                    )
                    # Keep context usage telemetry aligned with Agent.process_message()
                    agent.context_injection_count = int(
                        getattr(agent, "context_injection_count", 0)
                    ) + 1
                    agent.context_docs_loaded = int(
                        getattr(agent, "context_docs_loaded", 0)
                    ) + len(contexts)
                else:
                    message_with_context = message
            except Exception as e:
                print_agent_step(
                    name,
                    "Error",
                    f"Failed to load context: {e}",
                    model=agent.model,
                )
                message_with_context = message

            agent.history.append({"role": "user", "content": message_with_context})

        # Run all agents in parallel - TRUE CONCURRENCY
        tasks = []
        for name, agent in self.agents.items():
            tasks.append(agent.autonomous_loop())

        await asyncio.gather(*tasks, return_exceptions=True)

        return "All agents completed."

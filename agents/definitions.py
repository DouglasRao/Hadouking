import json
from pathlib import Path


def load_agents():
    """
    Load agent definitions from `agents/configs/*.json`.
    Files whose names start with `_` (for example `_template_agent.json`) are ignored.
    """
    agents = {}
    current_dir = Path(__file__).parent
    config_dir = current_dir / "configs"

    if not config_dir.exists():
        print(f"Warning: Config directory not found at {config_dir}")
        return agents

    for config_file in sorted(config_dir.glob("*.json")):
        if config_file.stem.startswith("_"):
            continue
        try:
            with open(config_file, "r") as f:
                config = json.load(f)
                agent_name = config_file.stem
                agents[agent_name] = config
        except Exception as e:
            print(f"Error loading agent config {config_file}: {e}")

    return agents

AGENTS = load_agents()

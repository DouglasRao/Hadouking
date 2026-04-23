import json
import os
from typing import Dict, Any, Optional


def _default_settings_path() -> str:
    """Resolve `settings.json` next to `utils/`, independent of CWD."""
    utils_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(utils_dir), "settings.json")


class MCPConfig:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or _default_settings_path()
        self.servers: Dict[str, Any] = {}
        self.load()

    def load(self):
        """Loads MCP configuration from settings.json"""
        if not os.path.exists(self.config_path):
            # Return an empty config when the file does not exist.
            return

        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
                self.servers = data.get("mcpServers", {})
        except Exception as e:
            print(f"Error loading MCP config: {e}")

    def get_server_config(self, server_name: str) -> Optional[Dict[str, Any]]:
        return self.servers.get(server_name)

    def list_servers(self) -> list[str]:
        return list(self.servers.keys())

"""Tests MCPConfig loading from `settings.json` in the project root."""

import unittest

from utils.mcp_config import MCPConfig


class TestMCPConfig(unittest.TestCase):
    def test_load_config_structure(self):
        cfg = MCPConfig()
        self.assertIsInstance(cfg.servers, dict)
        # Content depends on the local settings.json; only the structure is asserted here.
        for name, entry in cfg.servers.items():
            self.assertIsInstance(name, str)
            self.assertIsInstance(entry, dict)


if __name__ == "__main__":
    unittest.main()

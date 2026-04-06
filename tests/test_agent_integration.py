"""Smoke test: Agent initializes with context loader and validator."""

import unittest

from core.agent import Agent


class TestAgentIntegration(unittest.TestCase):
    def test_agent_init_context_and_validator(self):
        agent = Agent(
            name="test_agent",
            model="gpt-4o",
            system_prompt="You are a test agent.",
        )
        self.assertIsNotNone(agent.context_loader)
        self.assertIsNotNone(agent.tool_validator)

    def test_context_keywords_from_message(self):
        agent = Agent(
            name="bug_bounty_agent",
            model="gpt-4o",
            system_prompt="Test.",
        )
        keywords = agent.context_loader.extract_keywords(
            "I need to find XSS vulnerabilities"
        )
        self.assertIn("xss", keywords)


if __name__ == "__main__":
    unittest.main()

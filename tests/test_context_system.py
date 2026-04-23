import unittest
import os
from agents.context.loader import ContextLoader
from agents.tools.validator import ToolValidator

class TestContextSystem(unittest.TestCase):
    def setUp(self):
        self.loader = ContextLoader()
        self.validator = ToolValidator()
        
    def test_tool_validator(self):
        print("\nTesting ToolValidator...")
        available = self.validator.get_available_tools()
        print(f"Available tools: {len(available)}")
        self.assertTrue(len(available) > 0)
        
    def test_context_loader(self):
        print("\nTesting ContextLoader...")
        
        # Test keyword extraction
        text = "I need to scan for XSS and SQL injection"
        keywords = self.loader.extract_keywords(text)
        print(f"Extracted keywords: {keywords}")
        self.assertIn("xss", keywords)
        self.assertIn("sql", keywords)
        
        # Test context loading - Code Review (OWASP)
        contexts = self.loader.get_relevant_context("code_review_agent", ["xss"])
        self.assertTrue(len(contexts) > 0, "Should load OWASP context")
        self.assertIn("OWASP", contexts[0])
        
        # Test context loading - Recon Passive (PTES + OSINT Framework)
        contexts = self.loader.get_relevant_context("recon_passive_agent", [])
        self.assertTrue(len(contexts) > 0, "Should load context for recon_passive_agent")
        joined = "\n".join(contexts)
        self.assertIn("OSINT", joined)

        # Test context loading - Brain (PTES + OWASP + MITRE)
        contexts = self.loader.get_relevant_context("pentest_brain_agent", [])
        self.assertTrue(len(contexts) >= 2, "Should load multiple frameworks for brain agent")

        # Test context loading - API testing (OWASP)
        contexts = self.loader.get_relevant_context("api_testing_agent", [])
        joined = "\n".join(contexts)
        self.assertIn("OWASP", joined)

if __name__ == '__main__':
    unittest.main()

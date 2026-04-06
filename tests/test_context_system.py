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
        
        # Test context loading - Bug Bounty (OWASP)
        contexts = self.loader.get_relevant_context("bug_bounty_agent", ["xss"])
        self.assertTrue(len(contexts) > 0, "Should load OWASP context")
        self.assertIn("OWASP", contexts[0])
        
        # Test context loading - Android (MASVS)
        contexts = self.loader.get_relevant_context("android_sast_agent", [])
        self.assertTrue(len(contexts) > 0, "Should load MASVS context")
        self.assertIn("MASVS", contexts[0])
        
        # Test context loading - Network (OSSTMM)
        contexts = self.loader.get_relevant_context("network_security_analyzer_agent", [])
        self.assertTrue(len(contexts) > 0, "Should load OSSTMM context")
        self.assertIn("OSSTMM", contexts[0])
        
        # Test context loading - OSINT (OSINT Framework)
        contexts = self.loader.get_relevant_context("osint_agent", [])
        self.assertTrue(len(contexts) > 0, "Should load OSINT Framework context")
        self.assertIn("OSINT Framework", contexts[0])

if __name__ == '__main__':
    unittest.main()

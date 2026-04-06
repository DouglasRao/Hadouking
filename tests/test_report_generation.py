import unittest
import asyncio
import os
import shutil
from core.agent import Agent
from core.report_generator import ReportGenerator

class MockLLM:
    def __init__(self, model):
        self.model = model
    
    def supports_vision(self):
        return False
        
    async def generate(self, history, image_base64=None):
        return "I have finished scanning. No vulnerabilities found."

class TestReportGeneration(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(
            name="TestAgent",
            model="gpt-4o",
            system_prompt="You are a test agent."
        )
        # Mock LLM to avoid API calls
        self.agent.llm = MockLLM("gpt-4o")
        
    def test_report_generation_on_stop(self):
        async def run_test():
            # Simulate some activity
            self.agent.report_generator.set_target("example.com")
            self.agent.report_generator.add_finding("Test Vuln", "High", "Description", "Fix it")
            
            # Stop agent
            summary = await self.agent.stop()
            
            # Check if report file exists in project directory
            project_dir = self.agent.project_dir
            files = os.listdir(project_dir)
            report_files = [f for f in files if f.startswith("pentest_report_example.com")]
            self.assertTrue(len(report_files) > 0, "Report file not created in project dir")
            
            # Clean up
            # shutil.rmtree(project_dir) # Optional: keep for inspection or delete
                
        asyncio.run(run_test())

if __name__ == '__main__':
    unittest.main()

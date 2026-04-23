import unittest
from collections import deque
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent import Agent

class TestLoopPrevention(unittest.TestCase):
    def setUp(self):
        # Mock minimal agent initialization
        self.agent = Agent(
            name="TestAgent",
            model="test-model",
            system_prompt="test prompt",
            limit=10
        )
        # Reset history for test
        self.agent.command_history = deque(maxlen=10)

    def test_detect_loop_true(self):
        """Test that loop is detected after 2 repetitions (3rd attempt)"""
        cmd = "ls -la"
        self.agent.command_history.append(cmd)
        self.agent.command_history.append(cmd)
        
        # Should detect loop on 3rd attempt
        self.assertTrue(self.agent._detect_loop(cmd))

    def test_detect_loop_false_different_command(self):
        """Test that loop is NOT detected if commands differ"""
        self.agent.command_history.append("ls -la")
        self.agent.command_history.append("whoami")
        
        self.assertFalse(self.agent._detect_loop("ls -la"))

    def test_detect_loop_false_not_enough_history(self):
        """Test that loop is NOT detected with insufficient history"""
        self.agent.command_history.append("ls -la")
        
        self.assertFalse(self.agent._detect_loop("ls -la"))

if __name__ == '__main__':
    unittest.main()

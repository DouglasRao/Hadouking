import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.agent import Agent

async def _run_compaction_demo():
    print("Setting up test...")
    
    # Mock LLM
    mock_llm = MagicMock()
    mock_llm.model = "gpt-4"
    mock_llm.generate = AsyncMock(return_value="[MOCK SUMMARY: The user asked to test compaction. We executed some commands. Everything is fine.]")
    
    # Create Agent with mocked LLM
    agent = Agent("TestAgent", "gpt-4", "System Prompt")
    agent.llm = mock_llm
    
    # Populate history with tool output
    agent.history = [
        {"role": "system", "content": "System Prompt"},
        {"role": "user", "content": "Run command"},
        {"role": "assistant", "content": "```bash\nls -la\n```"},
        {"role": "user", "content": "Command: ls -la\nOutput:\ntotal 0\n"},
        {"role": "assistant", "content": "Ok"},
        {"role": "user", "content": "Next"},
        {"role": "assistant", "content": "Response"},
        {"role": "user", "content": "More"},
        {"role": "assistant", "content": "More Response"},
        {"role": "user", "content": "Even More"},
    ]
    
    print(f"Initial history length: {len(agent.history)}")
    
    # Trigger compaction
    print("Triggering compaction...")
    await agent.compact_history()
    
    # Verify what was sent to LLM
    call_args = mock_llm.generate.call_args
    sent_messages = call_args[0][0]
    sent_content = sent_messages[1]["content"]
    
    print(f"Sent content preview:\n{sent_content[:200]}...")
    
    if "TOOL OUTPUT: Command: ls -la" not in sent_content:
        print("FAILED: Tool output not formatted correctly")
        print(f"Actual content:\n{sent_content}")
        return

    print("SUCCESS: Compaction logic and formatting verified!")

if __name__ == "__main__":
    asyncio.run(_run_compaction_demo())

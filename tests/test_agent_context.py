import asyncio
from core.agent import Agent

async def _run_agent_context_demo():
    print("\nTesting Agent Context Integration...")
    try:
        agent = Agent(
            name="test_agent",
            model="gpt-4o",
            system_prompt="You are a test agent."
        )
        print("Agent initialized successfully.")
        
        # Check if tool context was injected into history
        system_msg = agent.history[0]["content"]
        if "Available Security Tools" in system_msg:
            print("SUCCESS: Tool context injected into system prompt.")
        else:
            print("FAILURE: Tool context NOT found in system prompt.")
            
        # Test keyword extraction via agent
        msg = "I need to find XSS vulnerabilities"
        keywords = agent.context_loader.extract_keywords(msg)
        print(f"Agent extracted keywords: {keywords}")
        
    except Exception as e:
        print(f"Agent initialization failed: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(_run_agent_context_demo())

import asyncio
import sys
import os
import json
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analyzer import OutputAnalyzer

async def _run_analyzer_demo():
    print("Testing OutputAnalyzer...")
    
    # Mock LLM
    analyzer = OutputAnalyzer("test-model")
    analyzer.llm = MagicMock()
    analyzer.llm.generate = AsyncMock()
    
    # Test Case 1: Relevant Output
    print("\nTest Case 1: Relevant Output")
    analyzer.llm.generate.return_value = json.dumps({
        "relevant": True,
        "summary": "Found open port 80.",
        "new_tasks": ["Scan port 80"]
    })
    
    result = await analyzer.analyze("nmap -p 80 localhost", "PORT STATE SERVICE\n80/tcp open http")
    print(f"Result: {result}")
    assert result["relevant"] == True
    assert result["summary"] == "Found open port 80."
    assert "Scan port 80" in result["new_tasks"]
    print("PASS")

    # Test Case 2: Irrelevant Output
    print("\nTest Case 2: Irrelevant Output")
    analyzer.llm.generate.return_value = json.dumps({
        "relevant": False,
        "summary": "",
        "new_tasks": []
    })
    
    result = await analyzer.analyze("ls", "file1.txt file2.txt")
    print(f"Result: {result}")
    assert result["relevant"] == False
    print("PASS")

    # Test Case 3: JSON Error Recovery
    print("\nTest Case 3: JSON Error Recovery")
    analyzer.llm.generate.return_value = "Invalid JSON"
    
    result = await analyzer.analyze("cmd", "output")
    print(f"Result: {result}")
    assert result["relevant"] == True # Should default to true
    assert "Analyzer failed to parse JSON" in result["summary"]
    print("PASS")

if __name__ == "__main__":
    asyncio.run(_run_analyzer_demo())

import json

from .llm import LLM
from utils.ui import ThinkingStatus, model_display_label

class OutputAnalyzer:
    def __init__(self, model_name, auth_manager=None):
        self.llm = LLM(model_name, auth_manager=auth_manager)
        self.system_prompt = """You are an expert cybersecurity analyst assistant. Your role is to analyze the output of various security tools (like Nmap, Burp Suite, etc.) and determine if the information is relevant to the current objective.

Your goal is to PREVENT INFORMATION OVERLOAD. You must filter out noise and only keep what is actionable or significant.

You will receive:
1. The Command that was executed.
2. The Output of that command.
3. A Summary of the current Context/Objective.

You must respond with a JSON object in the following format:
{
  "relevant": boolean, // true if the output contains useful information, false if it's noise or empty
  "summary": string, // A concise summary of the FINDINGS. Do not repeat the full output. If irrelevant, leave empty.
  "new_tasks": [string] // A list of suggested follow-up tasks based on this output.
}

CRITICAL RULES:
- If the output is just a progress bar, "starting...", or empty, set "relevant": false.
- If the output contains errors that prevent progress, set "relevant": true and summarize the error.
- If the output contains vulnerabilities, open ports, or interesting data, set "relevant": true and summarize the specific findings.
- Be extremely concise in your summary.
"""

    async def analyze(self, command, output, context_summary=""):
        """
        Analyzes the command output and returns a structured result.
        """
        # Keep the beginning and end because those sections usually contain the signal.
        max_output_chars = 20000  # ~5k tokens
        if len(output) > max_output_chars:
            half = max_output_chars // 2
            truncated_output = (
                output[:half]
                + "\n\n... [OUTPUT TRUNCATED FOR ANALYSIS] ...\n\n"
                + output[-half:]
            )
        else:
            truncated_output = output

        prompt = f"""
[CONTEXT SUMMARY]
{context_summary}

[COMMAND]
{command}

[OUTPUT]
{truncated_output}
"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        lbl = model_display_label(self.llm.model)
        with ThinkingStatus(f"Output analyzer ({lbl})..."):
            try:
                response_text = await self.llm.generate(messages)
                # Strip markdown fences if the model wrapped the JSON payload.
                response_text = response_text.strip()
                if response_text.startswith("```json"):
                    response_text = response_text[7:]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]

                result = json.loads(response_text.strip())
                return result
            except json.JSONDecodeError:
                # Fall back to a minimal structured error when the model returns invalid JSON.
                return {
                    "relevant": True,
                    "summary": f"Analyzer failed to parse JSON. Raw response: {response_text[:100]}...",
                    "new_tasks": [],
                }
            except Exception as e:
                return {
                    # Default to relevant if analysis fails so the runtime does not drop data.
                    "relevant": True,
                    "summary": f"Analyzer Error: {str(e)}",
                    "new_tasks": [],
                }

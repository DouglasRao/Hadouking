import tiktoken
from typing import List, Dict, Any

def count_tokens(messages: List[Dict[str, Any]], model: str = "gpt-4") -> int:
    """
    Count the number of tokens used by a list of messages.
    Adapted from OpenAI's cookbook and CAI's implementation.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    num_tokens = 0
    for message in messages:
        # every message follows <|start|>{role/name}\n{content}<|end|>\n
        num_tokens += 4
        for key, value in message.items():
            if isinstance(value, str):
                num_tokens += len(encoding.encode(value))
            elif isinstance(value, list):
                # Handle tool calls or other list content
                for item in value:
                    if isinstance(item, dict):
                         for k, v in item.items():
                             if isinstance(v, str):
                                 num_tokens += len(encoding.encode(v))
    
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens

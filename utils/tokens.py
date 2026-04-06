from typing import Any, Dict, List

import tiktoken


def _encode_length(encoding: tiktoken.Encoding, value: Any) -> int:
    """Estimate token usage for nested message values."""
    if isinstance(value, str):
        return len(encoding.encode(value))
    if isinstance(value, list):
        return sum(_encode_length(encoding, item) for item in value)
    if isinstance(value, dict):
        return sum(_encode_length(encoding, nested) for nested in value.values())
    return 0

def count_tokens(messages: List[Dict[str, Any]], model: str = "gpt-4") -> int:
    """
    Estimate token usage for chat-style message history.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    num_tokens = 0
    for message in messages:
        # Account for the approximate per-message framing used by chat models.
        num_tokens += 4
        num_tokens += _encode_length(encoding, message)

    # Reserve a small constant for the assistant reply prefix.
    num_tokens += 3
    return num_tokens

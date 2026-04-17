"""
Hadouking Guardrails: protection against destructive execution (check_command) and,
optionally, text injection (check_input — configurable for pentest).
"""

import re
import unicodedata
import base64
import logging
from typing import Tuple, List, Optional

from config import Config

logger = logging.getLogger(__name__)


class Guardrails:
    """Static security rules."""

    # Full mode: broad patterns (includes command injection attempts in text)
    INJECTION_PATTERNS_FULL: List[str] = [
        r"(?i)(ignore|disregard|forget|bypass|skip|override)\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|rules?|commands?|prompts?)",
        r"(?i)(new|updated?|revised?|changed?)\s+(instructions?|rules?|system\s+prompt)",
        r"(?i)you\s+(must|should|have\s+to|need\s+to)\s+(now|immediately)",
        r"(?i)(note|important|attention|warning)\s+to\s+(system|ai|assistant|model|agent|llm)",
        r"(?i)(system|admin|root)\s+(note|message|command|instruction)",
        r"(?i)<(system|admin|instruction|command|hidden)[^>]*>",
        r"(?i)(execute|run|eval|exec|os\.system|subprocess|shell)",
        r"(?i)\b(nc|netcat)\s+[\-\w]+",
        r"(?i)\b(bash|sh)\s+-\S",
        r"(?i)\bcmd(\.exe)?\s+/",
        r"(?i)\bpowershell\s+-\S",
        r"(?i)(send|transmit|export|leak|exfiltrate)\s+(data|information|secrets|credentials)",
        r"(?i)you\s+are\s+(now|actually|really)\s+a?\s*\w+",
        r"(?i)(act|behave|pretend)\s+(as|like)\s+a?\s*\w+",
    ]

    # Minimal mode: only clear system instruction manipulation (pentest / text payloads)
    INJECTION_PATTERNS_MINIMAL: List[str] = [
        r"(?i)(ignore|disregard|forget|bypass|skip|override)\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|rules?|commands?|prompts?)",
        r"(?i)(new|updated?|revised?|changed?)\s+(instructions?|rules?|system\s+prompt)",
        r"(?i)(note|important|attention|warning)\s+to\s+(system|ai|assistant|model|agent|llm)",
        r"(?i)(system|admin|root)\s+(note|message|command|instruction)",
        r"(?i)<(system|admin|instruction|command|hidden)[^>]*>",
        r"(?i)(act|behave|pretend)\s+(as|like)\s+a?\s*\w+",
        # Keep only shell invocation with flags (avoids blocking "bash commands" in prose)
        r"(?i)\b(bash|sh)\s+-\S",
    ]

    DANGEROUS_COMMANDS = [
        r"(?i)rm\s+-rf\s+/",
        r"(?i):(){ :|:& };:",
        r"(?i)nc\s+\d+\.\d+\.\d+\.\d+",
        r"(?i)curl.*\|.*sh",
        r"(?i)wget.*\|.*bash",
        r"(?i)/dev/tcp/",
        r"(?i)echo.*>>\s*/etc/",
        r"(?i)bash.*-i.*>&",
        r"(?i)socat\s+TCP:\d+\.\d+\.\d+\.\d+:\d+.*EXEC",
    ]

    @staticmethod
    def normalize_unicode_homographs(text: str) -> str:
        homograph_map = {
            "\u0430": "a",
            "\u0435": "e",
            "\u043e": "o",
            "\u0440": "p",
            "\u0441": "c",
            "\u0443": "y",
            "\u0445": "x",
            "\u03b1": "a",
            "\u03bf": "o",
            "\u03c1": "p",
            "\u2010": "-",
            "\u2011": "-",
            "\u2212": "-",
            "\uff0d": "-",
        }
        normalized = text
        for homograph, replacement in homograph_map.items():
            normalized = normalized.replace(homograph, replacement)
        return unicodedata.normalize("NFKD", normalized)

    @staticmethod
    def check_input(text: str) -> Tuple[bool, str]:
        """
        Filters input text (user / broadcast). Does not replace command validation.
        """
        if not text:
            return True, ""

        mode = Config.input_guardrails_mode()
        if mode == "off":
            return True, ""

        if text.lstrip().startswith("[AUTOTEST"):
            return True, ""

        normalized_text = Guardrails.normalize_unicode_homographs(text)
        patterns = (
            Guardrails.INJECTION_PATTERNS_FULL
            if mode == "full"
            else Guardrails.INJECTION_PATTERNS_MINIMAL
        )
        for pattern in patterns:
            if re.search(pattern, text) or re.search(pattern, normalized_text):
                return False, f"Suspicious pattern (input): {pattern}"

        if mode == "full" and re.search(r"base64|b64|BASE64", text):
            base64_pattern = r"[A-Za-z0-9+/]{20,}={0,2}"
            matches = re.findall(base64_pattern, text)
            for match in matches:
                try:
                    decoded = base64.b64decode(match).decode("utf-8", errors="ignore").lower()
                    if any(
                        danger in decoded
                        for danger in ["nc ", "netcat", "/bin/sh", "bash -i"]
                    ):
                        return False, "Suspicious base64 payload in text"
                except Exception:
                    pass

        return True, ""

    @staticmethod
    def check_command(command: str) -> Tuple[bool, str]:
        """
        Always active: blocks clearly destructive commands / classic reverse shells.
        """
        if not command:
            return True, ""

        normalized_cmd = Guardrails.normalize_unicode_homographs(command)
        for pattern in Guardrails.DANGEROUS_COMMANDS:
            if re.search(pattern, command) or re.search(pattern, normalized_cmd):
                return False, f"Command blocked (guardrails): {pattern}"

        if ("base64" in command.lower() or "base32" in command.lower()) and "-d" in command:
            if re.search(
                r"(base64|base32)\s+-d.*\|\s*(sh|bash|python|perl|ruby)",
                command,
                re.IGNORECASE,
            ):
                return False, "Decode-to-shell blocked"

        return True, ""

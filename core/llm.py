import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from config import Config, _HAS_AIOHTTP

if _HAS_AIOHTTP:
    import aiohttp


class LLM:
    """
    Unified generation: OpenAI-style APIs, Anthropic Messages API (Console API key and/or Bearer
    ANTHROPIC_AUTH_TOKEN like Claude Code), or CLIs (`claude-code-cli` / `openai-codex-cli`).
    """

    BACKEND_OPENAI_COMPAT = "openai_compat"
    BACKEND_ANTHROPIC = "anthropic"
    BACKEND_CLAUDE_CLI = "claude_cli"
    BACKEND_CODEX_CLI = "codex_cli"

    def __init__(self, model_name=None, auth_manager=None):
        self.model = model_name or Config.DEFAULT_MODEL
        self.auth_manager = auth_manager
        self.api_key = None
        self._anthropic_bearer: Optional[str] = None
        self.endpoint = None
        self.backend = self.BACKEND_OPENAI_COMPAT
        self.is_auto_rotate = self.model == "auto-rotate-free"
        self._rotator = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._configure()

    def _configure(self):
        if self.model == Config.MODEL_CLAUDE_CODE_CLI:
            self.backend = self.BACKEND_CLAUDE_CLI
            return
        if self.model == Config.MODEL_CODEX_CLI:
            self.backend = self.BACKEND_CODEX_CLI
            return

        if self.is_auto_rotate:
            from core.model_rotator import ModelRotator

            self._rotator = ModelRotator()
            self.api_key = Config.OPENROUTER_API_KEY
            self.endpoint = Config.OPENROUTER_ENDPOINT
            self.model = self._rotator.get_next_model()
            self.backend = self.BACKEND_OPENAI_COMPAT
            return

        m = self.model.lower()
        if any(p in m for p in ["nvidia/", "mistralai/", "qwen/", "google/", "deepseek/", "x-ai/"]):
            self.api_key = Config.OPENROUTER_API_KEY
            self.endpoint = Config.OPENROUTER_ENDPOINT
            self.backend = self.BACKEND_OPENAI_COMPAT
            return
        if "deepseek" in m and not m.startswith("deepseek/"):
            self.api_key = Config.DEEPSEEK_API_KEY
            self.endpoint = Config.DEEPSEEK_ENDPOINT
            self.backend = self.BACKEND_OPENAI_COMPAT
            return
        if self._is_anthropic_model_id(m):
            # Priority aligned with Claude Code IAM docs: Console API key first; otherwise Bearer (account/gateway)
            if Config.ANTHROPIC_API_KEY:
                self.api_key = Config.ANTHROPIC_API_KEY
                self._anthropic_bearer = None
                self.backend = self.BACKEND_ANTHROPIC
                return
            if Config.ANTHROPIC_AUTH_TOKEN:
                self.api_key = None
                self._anthropic_bearer = Config.ANTHROPIC_AUTH_TOKEN
                self.backend = self.BACKEND_ANTHROPIC
                return

        self.api_key = Config.OPENAI_API_KEY
        self.endpoint = Config.OPENAI_ENDPOINT
        self.backend = self.BACKEND_OPENAI_COMPAT

    @staticmethod
    def _is_anthropic_model_id(m: str) -> bool:
        return "claude" in m or m.startswith("anthropic/")

    def supports_vision(self):
        if self.model in (Config.MODEL_CLAUDE_CODE_CLI, Config.MODEL_CODEX_CLI):
            return False
        vision_markers = [
            "gpt-4o",
            "gpt-4-vision",
            "gpt-4-turbo",
            "claude-3",
            "claude-sonnet-4",
            "claude-opus-4",
            "gemini-2.0-flash",
            "gemini-1.5",
            "qwen3-vl",
            "qwen2.5-vl",
            "nemotron-nano-2-vl",
        ]
        return any(vm in self.model.lower() for vm in vision_markers)

    def _split_system_user_messages(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[str, List[Dict[str, Any]]]:
        system_parts: List[str] = []
        rest: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                c = msg.get("content", "")
                if isinstance(c, str):
                    system_parts.append(c)
                else:
                    system_parts.append(json.dumps(c))
            else:
                rest.append(msg)
        return "\n\n".join(system_parts), rest

    def _openai_messages_with_optional_image(
        self, messages: List[Dict[str, Any]], image_base64: Optional[str]
    ) -> List[Dict[str, Any]]:
        out = [dict(m) for m in messages]
        if image_base64 and self.supports_vision():
            for i in range(len(out) - 1, -1, -1):
                if out[i]["role"] == "user":
                    text_content = out[i]["content"]
                    if not isinstance(text_content, str):
                        break
                    out[i]["content"] = [
                        {"type": "text", "text": text_content},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                        },
                    ]
                    break
        return out

    def _anthropic_messages_payload(
        self, messages: List[Dict[str, Any]], image_base64: Optional[str]
    ) -> tuple[str, List[Dict[str, Any]]]:
        system_text, rest = self._split_system_user_messages(messages)
        anth_msgs: List[Dict[str, Any]] = []
        for i, msg in enumerate(rest):
            role = msg.get("role", "user")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                anth_msgs.append({"role": role, "content": content})
                continue
            is_last = i == len(rest) - 1
            if role == "user" and image_base64 and self.supports_vision() and is_last:
                anth_msgs.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": str(content)},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64,
                                },
                            },
                        ],
                    }
                )
            else:
                anth_msgs.append({"role": role, "content": str(content)})
        return system_text, anth_msgs

    async def generate(self, messages, image_base64=None, stream=False):
        """Generate a response. If stream=True, delegates to generate_stream (CLI backends fall back to blocking)."""
        if stream:
            if self.backend in (self.BACKEND_CLAUDE_CLI, self.BACKEND_CODEX_CLI):
                # CLI backends don't support streaming — fall back to blocking
                return await self._generate_blocking(messages, image_base64)
            collected = []
            async for chunk in self.generate_stream(messages, image_base64):
                collected.append(chunk)
            return "".join(collected)

        return await self._generate_blocking(messages, image_base64)

    async def _generate_blocking(self, messages, image_base64=None):
        """Non-streaming generation (original generate() logic)."""
        if self.is_auto_rotate and self._rotator:
            self.model = self._rotator.get_next_model()

        if self.backend == self.BACKEND_CLAUDE_CLI:
            return await self._generate_cli("claude", messages)
        if self.backend == self.BACKEND_CODEX_CLI:
            return await self._generate_cli("codex", messages)
        if self.backend == self.BACKEND_ANTHROPIC:
            return await self._generate_anthropic(messages, image_base64)
        return await self._generate_openai_compatible(messages, image_base64)

    async def generate_stream(self, messages, image_base64=None) -> AsyncGenerator[str, None]:
        """
        Async generator that yields text deltas via SSE streaming.
        CLI backends fall back to yielding a single blocking response.
        """
        if self.is_auto_rotate and self._rotator:
            self.model = self._rotator.get_next_model()

        if self.backend in (self.BACKEND_CLAUDE_CLI, self.BACKEND_CODEX_CLI):
            # CLI backends don't support streaming — yield the full result at once
            result = await self._generate_blocking(messages, image_base64)
            yield result
            return

        if self.backend == self.BACKEND_ANTHROPIC:
            async for chunk in self._stream_anthropic(messages, image_base64):
                yield chunk
            return

        # Default: OpenAI-compatible SSE streaming
        async for chunk in self._stream_openai_compatible(messages, image_base64):
            yield chunk

    async def _generate_cli(self, which: str, messages: List[Dict[str, Any]]) -> str:
        if not self.auth_manager:
            return "Error: auth_manager required for CLI backends"
        bridge = None
        if which == "claude" and self.auth_manager.claude_bridge.is_available():
            bridge = self.auth_manager.claude_bridge
        elif which == "codex" and self.auth_manager.codex_bridge.is_available():
            bridge = self.auth_manager.codex_bridge
        if not bridge:
            return f"Error: CLI '{which}' not available in PATH"
        try:
            return await bridge.send_prompt(messages, model=None)
        except Exception as e:
            return f"Error: CLI invoke failed: {e}"

    # ------------------------------------------------------------------ #
    #  Streaming helpers                                                   #
    # ------------------------------------------------------------------ #

    async def _stream_openai_compatible(
        self, messages: List[Dict[str, Any]], image_base64: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Yield text deltas from an OpenAI-compatible SSE stream."""
        if not self.api_key:
            yield "Error: no API key configured for this model/provider"
            return

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.endpoint == Config.OPENROUTER_ENDPOINT:
            headers["HTTP-Referer"] = "https://openrouter.ai"
            headers["X-Title"] = "Hadouking"

        msgs = self._openai_messages_with_optional_image(messages, image_base64)
        payload = {"model": self.model, "messages": msgs, "stream": True}

        try:
            session = await self._get_session()
            async with session.post(
                self.endpoint, headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    err = await response.text()
                    yield f"Error: {response.status} - {err}"
                    return
                async for raw_line in response.content:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data_str)
                            delta = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield f"Error calling API: {str(e)}"

    async def _stream_anthropic(
        self, messages: List[Dict[str, Any]], image_base64: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Yield text deltas from an Anthropic SSE stream."""
        bearer = self._anthropic_bearer or (
            (Config.ANTHROPIC_AUTH_TOKEN or "").strip() or None
        )
        api_key = Config.ANTHROPIC_API_KEY
        if not api_key and not bearer:
            yield (
                "Error: set ANTHROPIC_API_KEY (Console) or ANTHROPIC_AUTH_TOKEN "
                "(Bearer OAuth/account, like Claude Code). Optional: HADOUKING_USE_CLAUDE_CODE_CREDENTIALS=1 "
                "to read ~/.claude/.credentials.json."
            )
            return

        system_text, anth_msgs = self._anthropic_messages_payload(messages, image_base64)
        payload = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": anth_msgs,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text

        if api_key:
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": Config.ANTHROPIC_VERSION,
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer}",
                "anthropic-version": Config.ANTHROPIC_VERSION,
            }

        try:
            session = await self._get_session()
            async with session.post(
                Config.ANTHROPIC_ENDPOINT, headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    err = await response.text()
                    yield f"Error: {response.status} - {err}"
                    return
                async for raw_line in response.content:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            event = json.loads(data_str)
                            event_type = event.get("type", "")
                            if event_type == "content_block_delta":
                                delta = event.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    text = delta.get("text", "")
                                    if text:
                                        yield text
                            elif event_type == "message_stop":
                                return
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield f"Error calling API: {str(e)}"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=Config.HADOUKING_HTTP_TIMEOUT_SEC)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _generate_anthropic(self, messages, image_base64=None):
        bearer = self._anthropic_bearer or (
            (Config.ANTHROPIC_AUTH_TOKEN or "").strip() or None
        )
        api_key = Config.ANTHROPIC_API_KEY
        if not api_key and not bearer:
            return (
                "Error: set ANTHROPIC_API_KEY (Console) or ANTHROPIC_AUTH_TOKEN "
                "(Bearer OAuth/account, like Claude Code). Optional: HADOUKING_USE_CLAUDE_CODE_CREDENTIALS=1 "
                "to read ~/.claude/.credentials.json."
            )

        system_text, anth_msgs = self._anthropic_messages_payload(
            messages, image_base64
        )
        payload = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": anth_msgs,
        }
        if system_text:
            payload["system"] = system_text

        if api_key:
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": Config.ANTHROPIC_VERSION,
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer}",
                "anthropic-version": Config.ANTHROPIC_VERSION,
            }

        try:
            session = await self._get_session()
            async with session.post(
                Config.ANTHROPIC_ENDPOINT, headers=headers, json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    parts = data.get("content") or []
                    texts = [
                        p.get("text", "")
                        for p in parts
                        if p.get("type") == "text"
                    ]
                    return "".join(texts) if texts else json.dumps(data)
                err = await response.text()
                return f"Error: {response.status} - {err}"
        except Exception as e:
            return f"Error calling API: {str(e)}"

    async def _generate_openai_compatible(self, messages, image_base64=None):
        if not self.api_key:
            return "Error: no API key configured for this model/provider"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        if self.endpoint == Config.OPENROUTER_ENDPOINT:
            headers["HTTP-Referer"] = "https://openrouter.ai"
            headers["X-Title"] = "Hadouking"

        msgs = self._openai_messages_with_optional_image(messages, image_base64)
        payload = {"model": self.model, "messages": msgs, "stream": False}

        try:
            session = await self._get_session()
            async with session.post(
                self.endpoint, headers=headers, json=payload
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                error_text = await response.text()
                return f"Error: {response.status} - {error_text}"
        except Exception as e:
            return f"Error calling API: {str(e)}"

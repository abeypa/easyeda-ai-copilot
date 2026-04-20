"""
Anthropic Claude provider.
Supports claude-3-5-sonnet, claude-3-opus, claude-3-haiku, etc.
"""

from __future__ import annotations
import logging
from typing import AsyncIterator, List, Optional

import anthropic
from anthropic import AsyncAnthropic, APIConnectionError, AuthenticationError, RateLimitError

from .provider import LLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider."""

    DEFAULT_MODEL = "claude-3-5-haiku-latest"

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None):
        super().__init__(api_key, base_url, model)
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncAnthropic(**kwargs)

    def _fallback_model(self) -> str:
        return self.DEFAULT_MODEL

    def _split_messages(self, messages: List[LLMMessage]):
        """
        Anthropic separates system prompt from conversation messages.
        Returns (system_text, conversation_messages).
        """
        system_parts = [m.content for m in messages if m.role == "system"]
        conversation = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]
        return "\n\n".join(system_parts), conversation

    async def complete(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        resolved_model = self._resolve_model(model)
        system_text, conversation = self._split_messages(messages)

        try:
            kwargs: dict = {
                "model": resolved_model,
                "messages": conversation,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system_text:
                kwargs["system"] = system_text

            resp = await self.client.messages.create(**kwargs)
            content = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    content += block.text
            usage = {
                "prompt_tokens": resp.usage.input_tokens,
                "completion_tokens": resp.usage.output_tokens,
            }
            return LLMResponse(content=content, model=resolved_model, usage=usage)

        except AuthenticationError as e:
            raise ValueError(f"Anthropic authentication failed: {e}") from e
        except RateLimitError as e:
            raise ValueError(f"Anthropic rate limit exceeded: {e}") from e
        except APIConnectionError as e:
            raise ConnectionError(f"Anthropic connection error: {e}") from e

    async def stream(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        resolved_model = self._resolve_model(model)
        system_text, conversation = self._split_messages(messages)

        try:
            kwargs: dict = {
                "model": resolved_model,
                "messages": conversation,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if system_text:
                kwargs["system"] = system_text

            async with self.client.messages.stream(**kwargs) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    if text:
                        yield text

        except AuthenticationError as e:
            raise ValueError(f"Anthropic authentication failed: {e}") from e
        except RateLimitError as e:
            raise ValueError(f"Anthropic rate limit exceeded: {e}") from e
        except APIConnectionError as e:
            raise ConnectionError(f"Anthropic connection error: {e}") from e

    async def list_models(self) -> List[dict]:
        # Anthropic does not expose a public models list API — return known models
        return [
            {"id": "claude-opus-4-5", "name": "Claude Opus 4.5", "provider": "anthropic"},
            {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "provider": "anthropic"},
            {"id": "claude-3-5-sonnet-latest", "name": "Claude 3.5 Sonnet", "provider": "anthropic"},
            {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku", "provider": "anthropic"},
            {"id": "claude-3-opus-latest", "name": "Claude 3 Opus", "provider": "anthropic"},
            {"id": "claude-3-haiku-20240307", "name": "Claude 3 Haiku", "provider": "anthropic"},
        ]

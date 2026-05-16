"""
OpenAI provider — works with:
  - Direct OpenAI API (api.openai.com)
  - Any OpenAI-compatible API (Deepseek, Together, local Ollama, etc.)
  
Set base_url to override the endpoint.
"""

from __future__ import annotations
import logging
from typing import AsyncIterator, List, Optional

import httpx
from openai import AsyncOpenAI, APIConnectionError, AuthenticationError, RateLimitError

from .provider import LLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI (and compatible) LLM provider."""

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None):
        super().__init__(api_key, base_url, model)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            http_client=httpx.AsyncClient(timeout=120.0),
        )

    def _fallback_model(self) -> str:
        return self.DEFAULT_MODEL

    def _to_openai_messages(self, messages: List[LLMMessage]) -> List[dict]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def complete(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        resolved_model = self._resolve_model(model)
        kwargs: dict = {
            "model": resolved_model,
            "messages": self._to_openai_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        try:
            resp = await self.client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content or ""
            usage = {}
            if resp.usage:
                usage = {
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                }
            return LLMResponse(content=content, model=resolved_model, usage=usage)

        except AuthenticationError as e:
            raise ValueError(f"OpenAI authentication failed: {e}") from e
        except RateLimitError as e:
            raise ValueError(f"OpenAI rate limit exceeded: {e}") from e
        except APIConnectionError as e:
            raise ConnectionError(f"OpenAI connection error: {e}") from e

    async def stream(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        resolved_model = self._resolve_model(model)
        try:
            # Use create(stream=True) — compatible with all openai SDK v1.x versions.
            # .text_stream does not exist on AsyncChatCompletionStream in openai<1.12.
            stream = await self.client.chat.completions.create(
                model=resolved_model,
                messages=self._to_openai_messages(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta

        except AuthenticationError as e:
            raise ValueError(f"OpenAI authentication failed: {e}") from e
        except RateLimitError as e:
            raise ValueError(f"OpenAI rate limit exceeded: {e}") from e
        except APIConnectionError as e:
            raise ConnectionError(f"OpenAI connection error: {e}") from e

    async def list_models(self) -> List[dict]:
        try:
            models = await self.client.models.list()
            result = []
            for m in models.data:
                result.append({
                    "id": m.id,
                    "name": m.id,
                    "provider": "openai",
                })
            # Sort: put gpt models first
            result.sort(key=lambda x: (0 if "gpt" in x["id"] else 1, x["id"]))
            return result
        except Exception as e:
            logger.warning(f"Failed to list OpenAI models: {e}")
            # Return a sensible default list
            return [
                {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai"},
                {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "openai"},
                {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "provider": "openai"},
                {"id": "o1", "name": "o1", "provider": "openai"},
                {"id": "o1-mini", "name": "o1-mini", "provider": "openai"},
            ]

"""
OpenRouter provider — proxies any model through openrouter.ai.
Uses the OpenAI-compatible API format.
Gives access to GPT-4, Claude, Mistral, Llama, Gemini, and more.
"""

from __future__ import annotations
import logging
from typing import AsyncIterator, List, Optional

import httpx
from openai import AsyncOpenAI

from .provider import LLMProvider, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(LLMProvider):
    """OpenRouter LLM provider (any model via openrouter.ai)."""

    DEFAULT_MODEL = "openai/gpt-4o-mini"

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None):
        super().__init__(api_key, base_url or OPENROUTER_BASE_URL, model)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.base_url,
            http_client=httpx.AsyncClient(
                timeout=120.0,
                headers={
                    "HTTP-Referer": "https://easyeda-ai-copilot.local",
                    "X-Title": "EasyEDA AI Copilot",
                },
            ),
        )

    def _fallback_model(self) -> str:
        return self.DEFAULT_MODEL

    def _to_messages(self, messages: List[LLMMessage]) -> List[dict]:
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
            "messages": self._to_messages(messages),
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
        except Exception as e:
            logger.error(f"OpenRouter completion error: {e}")
            raise

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
                messages=self._to_messages(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta
        except Exception as e:
            logger.error(f"OpenRouter stream error: {e}")
            raise

    async def list_models(self) -> List[dict]:
        """Fetch available models from OpenRouter."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = []
                    for m in data.get("data", []):
                        models.append({
                            "id": m.get("id", ""),
                            "name": m.get("name", m.get("id", "")),
                            "provider": "openrouter",
                            "context_length": m.get("context_length"),
                            "pricing": m.get("pricing"),
                        })
                    return sorted(models, key=lambda x: x["id"])
        except Exception as e:
            logger.warning(f"Failed to fetch OpenRouter models: {e}")

        # Fallback list with popular models
        return [
            {"id": "openai/gpt-4o", "name": "GPT-4o (via OpenRouter)", "provider": "openrouter"},
            {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini (via OpenRouter)", "provider": "openrouter"},
            {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet (via OpenRouter)", "provider": "openrouter"},
            {"id": "anthropic/claude-3-haiku", "name": "Claude 3 Haiku (via OpenRouter)", "provider": "openrouter"},
            {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat (via OpenRouter)", "provider": "openrouter"},
            {"id": "google/gemini-flash-1.5", "name": "Gemini Flash 1.5 (via OpenRouter)", "provider": "openrouter"},
            {"id": "meta-llama/llama-3.1-8b-instruct", "name": "Llama 3.1 8B (via OpenRouter)", "provider": "openrouter"},
            {"id": "mistralai/mistral-7b-instruct", "name": "Mistral 7B (via OpenRouter)", "provider": "openrouter"},
        ]

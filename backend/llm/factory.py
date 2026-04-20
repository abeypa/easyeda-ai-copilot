"""
LLM provider factory.
Creates the appropriate provider based on llmSettings.provider from the frontend.
"""

from __future__ import annotations
import logging
from typing import Optional

from models.circuit import LLMSettings
from .provider import LLMProvider
from .openai_provider import OpenAIProvider
from .anthropic_provider import AnthropicProvider
from .openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


def get_provider(llm_settings: LLMSettings) -> LLMProvider:
    """
    Instantiate the correct LLM provider from LLMSettings.
    
    Provider selection:
      - "openai"     → OpenAIProvider (also works for Deepseek, Together, etc. via base-url)
      - "anthropic"  → AnthropicProvider
      - "openrouter" → OpenRouterProvider
      - anything else → tries OpenAI-compatible
    
    Raises ValueError if no API key is provided.
    """
    provider_name = (llm_settings.provider or "openai").lower()
    api_key = llm_settings.apiKey or ""
    base_url = llm_settings.base_url

    if not api_key:
        raise ValueError(
            f"No API key configured for provider '{provider_name}'. "
            "Please add your API key in the extension Settings panel."
        )

    # Resolve default model from base agent settings
    default_model: Optional[str] = None
    if llm_settings.base and llm_settings.base.model:
        default_model = llm_settings.base.model

    if provider_name == "anthropic":
        logger.info(f"Using Anthropic provider (model: {default_model or 'default'})")
        return AnthropicProvider(api_key=api_key, base_url=base_url, model=default_model)

    elif provider_name == "openrouter":
        logger.info(f"Using OpenRouter provider (model: {default_model or 'default'})")
        return OpenRouterProvider(api_key=api_key, base_url=base_url, model=default_model)

    else:
        # Default: OpenAI or OpenAI-compatible
        if provider_name not in ("openai",):
            logger.warning(
                f"Unknown provider '{provider_name}', falling back to OpenAI-compatible. "
                f"Set base-url if you're using a custom endpoint."
            )
        logger.info(f"Using OpenAI provider (model: {default_model or 'default'}, base_url: {base_url})")
        return OpenAIProvider(api_key=api_key, base_url=base_url, model=default_model)

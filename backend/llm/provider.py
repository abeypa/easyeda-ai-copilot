"""
Abstract LLM provider interface.
All concrete providers must implement this interface.
"""

from __future__ import annotations
import abc
import json
import re
from typing import AsyncIterator, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    """A single message in a conversation."""
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """Non-streaming response from the LLM."""
    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)

    def extract_json(self) -> Any:
        """
        Try to extract a JSON object or array from the response content.
        Handles LLMs that wrap JSON in markdown code fences, explanation text,
        or return multiple fenced blocks.
        """
        text = self.content.strip()

        # Strategy 1: Extract from markdown code fences (get ALL fenced blocks)
        fence_matches = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        for fenced in fence_matches:
            fenced = fenced.strip()
            if fenced:
                try:
                    return json.loads(fenced)
                except json.JSONDecodeError:
                    pass

        # Strategy 2: Find the LARGEST balanced JSON array or object in the text
        # (prefer arrays since our agents return arrays)
        candidates = []
        for start_char, end_char in [('[', ']'), ('{', '}')]:
            search_from = 0
            while True:
                start = text.find(start_char, search_from)
                if start == -1:
                    break
                depth = 0
                in_string = False
                escape_next = False
                found_end = -1
                for i, ch in enumerate(text[start:], start):
                    if escape_next:
                        escape_next = False
                        continue
                    if ch == '\\' and in_string:
                        escape_next = True
                        continue
                    if ch == '"' and not escape_next:
                        in_string = not in_string
                    if not in_string:
                        if ch == start_char:
                            depth += 1
                        elif ch == end_char:
                            depth -= 1
                            if depth == 0:
                                found_end = i
                                break
                if found_end != -1:
                    candidate = text[start:found_end + 1]
                    try:
                        parsed = json.loads(candidate)
                        candidates.append((len(candidate), parsed))
                    except json.JSONDecodeError:
                        pass
                    search_from = found_end + 1
                else:
                    break

        if candidates:
            # Return the largest valid JSON (most likely the full response)
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        # Strategy 3: Last resort — try the whole thing
        return json.loads(text)


class LLMProvider(abc.ABC):
    """Abstract base class for all LLM providers."""

    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = model

    @abc.abstractmethod
    async def complete(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """Generate a non-streaming completion."""
        ...

    @abc.abstractmethod
    async def stream(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.5,
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        """
        Generate a streaming completion.
        Yields text chunks as they arrive.
        """
        ...

    @abc.abstractmethod
    async def list_models(self) -> List[dict]:
        """Return a list of available model dicts with at least 'id' and 'name'."""
        ...

    def _resolve_model(self, model: Optional[str]) -> str:
        """Return the model to use, falling back to the provider default."""
        return model or self.default_model or self._fallback_model()

    def _fallback_model(self) -> str:
        return "gpt-4o-mini"

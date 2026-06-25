"""Unified LLM provider types and base protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderNotConfiguredError(Exception):
    """Raised when the requested provider has no API key configured."""


class UnknownProviderError(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"unknown LLM provider: {name}")


@dataclass
class LlmProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LlmProviderTextResult:
    raw_text: str | None
    usage: LlmProviderUsage
    finish_reason: str | None
    provider: str
    model: str
    transport_ok: bool
    error: str | None = None
    raw_response_preview: str | None = None
    response_format: str | None = None
    request_payload_redacted: dict[str, Any] = field(default_factory=dict)
    response_payload: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    fallback_raw_response_used: bool = False


@dataclass
class LlmProviderResponse:
    provider: str
    model: str
    raw_text: str
    parsed_json: dict[str, Any] | None
    usage: LlmProviderUsage
    finish_reason: str | None
    request_payload_redacted: dict[str, Any]
    response_payload: dict[str, Any]
    latency_ms: int
    error_message: str | None = None
    transport_ok: bool = True
    response_format: str | None = None


class LlmProvider(Protocol):
    name: str

    async def complete_text(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        timeout_seconds: int = 60,
        json_mode: bool = False,
    ) -> LlmProviderTextResult:
        ...

    async def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_schema: dict[str, Any] | None = None,
        timeout_seconds: int = 60,
    ) -> LlmProviderResponse:
        ...

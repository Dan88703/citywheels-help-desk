"""A tiny model interface plus one real implementation.

The agent only depends on `ChatModel.complete()`. Tests plug in a scripted
fake model; the CLI uses `OpenAICompatibleModel`, which talks to any
provider with an OpenAI-style chat completions endpoint. That one adapter
covers Google Gemini (its OpenAI-compatible endpoint), GitHub Models, Groq
and a local Ollama, so switching providers is a change in .env only.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict | str  # str when the model sent JSON we could not parse
    # Provider-specific data that must be sent back unchanged with this call
    # in the history. Gemini 3 puts its "thought signature" here and rejects
    # the next request (HTTP 400) if it is missing.
    extra_content: dict | None = None


@dataclass
class ModelResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse: ...


def _parse_arguments(raw: str | None) -> dict | str:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw  # the tool dispatcher reports it as invalid_arguments


class OpenAICompatibleModel:
    def __init__(self, model: str, api_key: str, base_url: str | None = None, temperature: float = 0.0):
        from openai import OpenAI  # imported lazily so tests don't need the package

        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self._client = OpenAI(api_key=api_key, base_url=base_url or None)

    @classmethod
    def from_env(cls) -> "OpenAICompatibleModel":
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_API_KEY is not set. Copy .env.example to .env and fill it in.")
        return cls(
            model=os.getenv("LLM_MODEL", "openai/gpt-oss-120b"),
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        )

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=self.temperature,
        )
        # When the server answers with something that is not JSON (an HTML
        # error page, a plain-text "Unauthorized", a wrong URL), the SDK hands
        # back the raw text instead of a ChatCompletion. Fail with that text,
        # so the real cause is visible.
        if isinstance(response, str) or not getattr(response, "choices", None):
            raise RuntimeError(
                f"Unexpected response from {self.base_url} for model '{self.model}': "
                f"{str(response)[:300]!r}. Check LLM_BASE_URL, LLM_MODEL and LLM_API_KEY."
            )
        message = response.choices[0].message
        calls = [
            ToolCall(
                id=c.id,
                name=c.function.name,
                arguments=_parse_arguments(c.function.arguments),
                # Not part of the OpenAI schema, so the SDK keeps it as an extra field.
                extra_content=(c.model_extra or {}).get("extra_content"),
            )
            for c in (message.tool_calls or [])
        ]
        return ModelResponse(text=message.content, tool_calls=calls)

"""Shared OpenAI client plus a helper that returns Pydantic-validated structured output."""

from __future__ import annotations

import os
from typing import Optional, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")
# Reasoning effort for reasoning models (minimal | low | medium | high). Set to "" to omit it,
# which is required for non-reasoning models such as gpt-4.1.
EFFORT = os.environ.get("OPENAI_REASONING_EFFORT", "medium")

T = TypeVar("T", bound=BaseModel)

_client: Optional[AsyncOpenAI] = None


class AgentError(Exception):
    """The model refused, or returned nothing parseable."""


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        # OPENAI_API_KEY is the standard name; OPENAI_KEY is what the Vercel project uses.
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
        _client = AsyncOpenAI(api_key=api_key, max_retries=3)
    return _client


async def structured(system: str, user: str, output_model: Type[T], effort: Optional[str] = None) -> T:
    effort = EFFORT if effort is None else effort
    response = await client().responses.parse(
        model=MODEL,
        instructions=system,
        input=user,
        text_format=output_model,
        reasoning={"effort": effort} if EFFORT and effort else None,
        max_output_tokens=16000,
        store=False,
    )
    if response.status == "incomplete":
        reason = response.incomplete_details.reason if response.incomplete_details else "unknown"
        raise AgentError(f"model output was incomplete ({reason})")
    for item in response.output:
        for part in getattr(item, "content", None) or []:
            if part.type == "refusal":
                raise AgentError(f"model declined the request: {part.refusal}")
    if response.output_parsed is None:
        raise AgentError("model returned no structured output")
    return response.output_parsed

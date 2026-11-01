
# -*- coding: utf-8 -*-
"""Agenda parsing module using Anthropic Claude on Amazon Bedrock."""

from __future__ import annotations

import json
import logging
import os
import time

from datetime import date, datetime
from typing import Any

from anthropic import AnthropicBedrock
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("meetings.ai.agenda")

# Default model configuration
DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"

# Pricing: Claude Sonnet 4.6
INPUT_COST_PER_MTOK = 3.00
OUTPUT_COST_PER_MTOK = 15.00


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgendaItem(BaseModel):
    """Single agenda item."""

    model_config = ConfigDict(extra="ignore")

    topic: str
    owner: str | None = None
    minutes: int | None = None


class ActionItem(BaseModel):
    """Action item derived from the agenda."""

    model_config = ConfigDict(extra="ignore")

    task: str
    owner: str | None = None
    due: date | None = None


class ParsedAgenda(BaseModel):
    """Full parsed agenda returned by the LLM."""

    model_config = ConfigDict(
        extra="ignore",
        json_encoders={
            datetime: lambda v: v.isoformat(),
            date: lambda v: v.isoformat(),
        },
    )

    title: str
    starts_at: datetime
    duration_minutes: int
    items: list[AgendaItem] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    language: str | None = None


# ---------------------------------------------------------------------------
# Claude tool definition
# ---------------------------------------------------------------------------

record_agenda = {
    "name": "record_agenda",
    "description": "Return the parsed meeting agenda in structured format.",
    "input_schema": ParsedAgenda.model_json_schema(),
}


# ---------------------------------------------------------------------------
# Bedrock client
# ---------------------------------------------------------------------------

def _get_client() -> AnthropicBedrock:
    """Create Anthropic Bedrock client."""

    region = os.getenv("AWS_REGION", DEFAULT_REGION)

    return AnthropicBedrock(
        aws_region=region,
    )


# ---------------------------------------------------------------------------
# Agenda parser
# ---------------------------------------------------------------------------

def parse_agenda(
    text: str,
    today: date,
    tz: str,
) -> tuple[ParsedAgenda, dict[str, Any]]:
    """Parse raw agenda text into a structured ParsedAgenda."""

    client = _get_client()

    model = os.getenv("PARSER_MODEL", DEFAULT_MODEL)

    prompt_version = "v1"

    system_prompt = (
        f"You are an expert meeting agenda parser. "
        f"Current date is {today.isoformat()} and timezone is {tz}.\n"
        "Convert the meeting agenda provided by the user into structured "
        "data using the record_agenda tool.\n"
        "Instructions:\n"
        "- Resolve relative dates and times using the current date and timezone.\n"
        "- Infer a suitable meeting title.\n"
        "- Extract starts_at as an ISO 8601 datetime with timezone offset.\n"
        "- Extract duration_minutes as an integer.\n"
        "- Extract all agenda items.\n"
        "- Extract action items, their owners and due dates when available.\n"
        "- Do not invent information that is not present in the input.\n"
        "- If information is missing, use null where the schema allows it.\n"
        "- If language is evident, record it (e.g. 'en', 'uk')."
    )

    start_time = time.time()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            tools=[record_agenda],
            tool_choice={
                "type": "tool",
                "name": "record_agenda",
            },
            messages=[
                {
                    "role": "user",
                    "content": text,
                }
            ],
        )

    except Exception:
        logger.exception(
            "Claude Bedrock request failed. Model=%s, Region=%s",
            model,
            os.getenv("AWS_REGION", DEFAULT_REGION),
        )
        raise

    latency_ms = int((time.time() - start_time) * 1000)

    # Extract tool input
    tool_input = None

    for content in response.content:
        if (
            getattr(content, "type", None) == "tool_use"
            and getattr(content, "name", None) == "record_agenda"
        ):
            tool_input = content.input
            break

    # Fallback for a text response containing JSON
    if tool_input is None:
        text_blocks = [
            content.text
            for content in response.content
            if getattr(content, "type", None) == "text"
        ]

        if not text_blocks:
            raise ValueError(
                "Claude returned neither tool input nor JSON text."
            )

        raw_text = text_blocks[0].strip()

        # Remove Markdown code fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[-1]

            if raw_text.endswith("```"):
                raw_text = raw_text.rsplit("```", 1)[0].strip()

        tool_input = json.loads(raw_text)

    # Validate response using Pydantic
    parsed = ParsedAgenda.model_validate(tool_input)

    # Token usage
    usage = getattr(response, "usage", None)

    input_tokens = (
        getattr(usage, "input_tokens", 0)
        if usage else 0
    )

    output_tokens = (
        getattr(usage, "output_tokens", 0)
        if usage else 0
    )

    # Calculate approximate API cost
    cost_usd = round(
        (input_tokens / 1_000_000 * INPUT_COST_PER_MTOK)
        + (output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK),
        6,
    )

    meta = {
        "model": model,
        "prompt_version": prompt_version,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
    }

    return parsed, meta

# -*- coding: utf-8 -*-
"""Agenda parsing module using Anthropic Bedrock (Anthropic Messages API on Bedrock).

Provides Pydantic models representing a meeting agenda and helper
function `parse_agenda` that calls the Claude model to convert a free-form
text agenda into structured data.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from typing import Any, Dict, Tuple

try:
    from anthropic import AnthropicBedrockMantle, AnthropicBedrock
except ImportError:
    AnthropicBedrockMantle = None
    AnthropicBedrock = None

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("meetings.ai.agenda")

# Pricing for anthropic.claude-sonnet-4-6: $3.00 / MTok in, $15.00 / MTok out
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
        json_encoders={datetime: lambda v: v.isoformat(), date: lambda v: v.isoformat()}
    )

    title: str
    starts_at: datetime
    duration_minutes: int
    items: list[AgendaItem] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    language: str | None = None


# Tool definition for Claude tool use
record_agenda = {
    "name": "record_agenda",
    "description": "Store a parsed agenda in the system.",
    "input_schema": ParsedAgenda.model_json_schema(),
}


def _get_client():
    region = os.getenv("AWS_REGION", "us-east-1")
    if AnthropicBedrockMantle is not None:
        try:
            return AnthropicBedrockMantle(aws_region=region)
        except Exception:
            pass
    if AnthropicBedrock is not None:
        return AnthropicBedrock(aws_region=region)
    raise RuntimeError("Anthropic Bedrock client is not available in environment.")


def parse_agenda(text: str, today: date, tz: str) -> Tuple[ParsedAgenda, Dict[str, Any]]:
    """Parse raw agenda text into a ParsedAgenda using Claude on Amazon Bedrock."""
    client = _get_client()
    # Use a Bedrock model that is available for this account.
    model = os.getenv("PARSER_MODEL", "anthropic.claude-sonnet-4-6")
    prompt_version = "v1"

    system_prompt = (
        f"You are an expert meeting agenda parser. Current date is {today.isoformat()} and timezone is {tz}.\n"
        "Convert the meeting agenda provided by the user into structured JSON matching the tool `record_agenda`.\n"
        "- Resolve relative dates and times based on the current date and timezone.\n"
        "- Infer title, starts_at (ISO 8601 with timezone or UTC offset), duration_minutes, agenda items, and action items.\n"
        "- If language is evident, record it (e.g. 'en', 'uk')."
    )

    start_time = time.time()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system_prompt,
            tools=[record_agenda],
            tool_choice={"type": "tool", "name": "record_agenda"},
            messages=[{"role": "user", "content": text}],
        )
    except Exception as exc:
        logger.warning("Tool call to Claude failed (%s), attempting text-based parse...", exc)
        # Fallback to direct prompt with schema instruction if tool call endpoint fails
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=(
                f"{system_prompt}\nReturn ONLY valid JSON matching this schema:\n"
                f"{json.dumps(ParsedAgenda.model_json_schema())}"
            ),
            messages=[{"role": "user", "content": text}],
        )

    latency_ms = int((time.time() - start_time) * 1000)

    # Extract parsed data from tool call or text content
    tool_input = None
    for content in response.content:
        if getattr(content, "type", None) == "tool_use" and getattr(content, "name", None) == "record_agenda":
            tool_input = content.input
            break

    if tool_input is None:
        raw_text = response.content[0].text.strip()
        # Strip potential markdown fences
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text.rsplit("```", 1)[0].strip()
        tool_input = json.loads(raw_text)

    parsed = ParsedAgenda.model_validate(tool_input)

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

    cost_usd = round(
        (input_tokens / 1_000_000.0 * INPUT_COST_PER_MTOK)
        + (output_tokens / 1_000_000.0 * OUTPUT_COST_PER_MTOK),
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

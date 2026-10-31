# -*- coding: utf-8 -*-
"""Agenda parsing module using Anthropic Bedrock.

Provides Pydantic models representing a meeting agenda and a helper
function `parse_agenda` that calls the Claude model to convert a free‑form
text agenda into structured data.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from typing import Tuple, Dict, Any

from anthropic import AnthropicBedrock, Completion, Message
from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AgendaItem(BaseModel):
    """Single agenda item.

    * ``topic`` – the subject of discussion.
    * ``owner`` – optional person responsible for the item.
    * ``minutes`` – optional allocated time in minutes.
    """

    topic: str
    owner: str | None = None
    minutes: int | None = None


class ActionItem(BaseModel):
    """Action‑item derived from the agenda.

    * ``task`` – description of the action.
    * ``owner`` – optional assignee.
    * ``due`` – optional due‑date (ISO format)."""

    task: str
    owner: str | None = None
    due: date | None = None


class ParsedAgenda(BaseModel):
    """Full parsed agenda returned by the LLM.

    * ``title`` – agenda title.
    * ``starts_at`` – start datetime of the meeting (UTC).
    * ``duration_minutes`` – total meeting length.
    * ``items`` – list of agenda items.
    * ``action_items`` – derived action items.
    * ``language`` – detected language (optional).
    """

    title: str
    starts_at: datetime
    duration_minutes: int
    items: list[AgendaItem]
    action_items: list[ActionItem]
    language: str | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat(), date: lambda v: v.isoformat()}

# ---------------------------------------------------------------------------
# Tool definition (used by the LLM in higher‑level workflows)
# ---------------------------------------------------------------------------

record_agenda = {
    "name": "record_agenda",
    "description": "Store a parsed agenda in the system.",
    "input_schema": ParsedAgenda.model_json_schema(),
}

# ---------------------------------------------------------------------------
# Helper – system prompt for the model
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an agenda‑parsing assistant. Convert the user‑provided free‑form "
    "meeting agenda into a JSON object that conforms exactly to the following "
    "schema (generated from the Pydantic model `ParsedAgenda`).\n"
    "- Preserve the order of items.\n"
    "- Resolve relative dates (e.g. ‘next Monday’) based on the supplied "
    "`today` date and `tz` timezone.\n"
    "- Leave any field that cannot be inferred as `null`.\n"
    "- Return **only** valid JSON – no explanations, no markdown.\n"
    "If the JSON fails validation, you will be asked to retry once with the "
    "validation error details."
)

# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def _call_model(messages: list[dict[str, str]]) -> Tuple[Message, Dict[str, Any]]:
    """Invoke Claude via Bedrock and return the raw response plus usage metadata.

    The function measures latency and extracts cost/usage information from the
    Bedrock response to be attached to the caller's telemetry.
    """

    region = os.getenv("AWS_REGION", "us-east-1")
    model = os.getenv("PARSER_MODEL", "anthropic.claude-opus-5-5")
    client = AnthropicBedrock(region_name=region)

    start = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=messages,
    )
    latency_ms = int((time.time() - start) * 1000)
    usage = getattr(response, "usage", None)
    meta = {
        "model": model,
        "prompt_version": "v1",
        "latency_ms": latency_ms,
        "cost_usd": getattr(usage, "total_cost", None) if usage else None,
    }
    return response, meta


def parse_agenda(text: str, today: date, tz: str) -> Tuple[ParsedAgenda, Dict[str, Any]]:
    """Parse a raw agenda text into a ``ParsedAgenda``.

    The function performs a single call to Claude. If the model's JSON output
    does **not** validate against ``ParsedAgenda`` a second attempt is made –
    the validation error is sent back to the model so it can correct the
    structure.
    """

    # First attempt
    messages = [{"role": "user", "content": text}]
    response, meta = _call_model(messages)
    raw = response.content[0].text.strip()
    try:
        agenda = ParsedAgenda.parse_raw(raw)
        return agenda, meta
    except ValidationError as err:
        # Second attempt with error details
        error_msg = f"Previous output failed validation: {err}\nPlease return valid JSON."
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": error_msg})
        response2, meta2 = _call_model(messages)
        raw2 = response2.content[0].text.strip()
        agenda = ParsedAgenda.parse_raw(raw2)
        # Merge usage metadata (sum latency, keep latest usage)
        meta2["latency_ms"] = meta.get("latency_ms", 0) + meta2.get("latency_ms", 0)
        return agenda, meta2

# ---------------------------------------------------------------------------
# Simple CLI entry‑point for manual testing (invoked via `make parse`)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from datetime import date

    txt = os.getenv("TEXT")
    if not txt:
        print("Set TEXT env var, e.g. make parse TEXT=\"My agenda…\"")
        sys.exit(1)
    agenda_obj, meta = parse_agenda(txt, date.today(), os.getenv("TZ", "UTC"))
    print(json.dumps(json.loads(agenda_obj.json()), ensure_ascii=False, indent=2))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


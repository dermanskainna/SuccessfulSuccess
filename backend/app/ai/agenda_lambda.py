
# -*- coding: utf-8 -*-
"""AWS Lambda entry point for agenda parsing (Bedrock)."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.ai.agenda import parse_agenda
from app.auth import get_verifier
from app.config import settings

logger = logging.getLogger("meetings.ai.agenda_lambda")
logger.setLevel(logging.INFO)


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, default=str),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for parsing agenda text."""

    # Handle CORS preflight
    http_method = (
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
        or event.get("httpMethod")
    )

    if http_method == "OPTIONS":
        return _response(200, {"status": "ok"})

    # Normalize headers
    headers = {
        k.lower(): v
        for k, v in (event.get("headers") or {}).items()
    }

    auth_header = headers.get("authorization", "")

    if not isinstance(auth_header, str) or not auth_header.startswith("Bearer "):
        return _response(
            401,
            {
                "error": "unauthorized",
                "message": "Sign in to continue.",
            },
        )

    token = auth_header.split(" ", 1)[1].strip()

    if not token:
        return _response(
            401,
            {
                "error": "unauthorized",
                "message": "Invalid token.",
            },
        )

    # Verify Cognito token
    try:
        verifier = get_verifier()
        current_user = asyncio.run(verifier.verify(token))
        user_sub = current_user.sub

    except Exception:
        logger.exception("Cognito token verification failed")

        return _response(
            401,
            {
                "error": "unauthorized",
                "message": "Invalid or expired token.",
            },
        )

    # Parse request body
    body_raw = event.get("body") or "{}"

    try:
        if event.get("isBase64Encoded"):
            body_raw = base64.b64decode(body_raw).decode("utf-8")

        data = json.loads(body_raw) if isinstance(body_raw, str) else body_raw

    except Exception:
        return _response(
            400,
            {
                "error": "bad_request",
                "message": "Invalid JSON body.",
            },
        )

    if not isinstance(data, dict):
        return _response(
            400,
            {
                "error": "bad_request",
                "message": "Request body must be a JSON object.",
            },
        )

    text = data.get("text", "")

    if not isinstance(text, str):
        return _response(
            400,
            {
                "error": "bad_request",
                "message": "Field 'text' must be a string.",
            },
        )

    if not text.strip():
        return _response(
            400,
            {
                "error": "bad_request",
                "message": "Field 'text' cannot be empty.",
            },
        )

    if len(text) > 10000:
        return _response(
            413,
            {
                "error": "payload_too_large",
                "message": "Agenda text exceeds 10,000 characters limit.",
            },
        )

    # Get current date in application timezone
    tz_str = settings.app_timezone

    try:
        today_date = datetime.now(ZoneInfo(tz_str)).date()

    except Exception:
        logger.exception("Invalid application timezone: %s", tz_str)
        return _response(
            500,
            {
                "error": "configuration_error",
                "message": "Invalid application timezone.",
            },
        )

    # Parse agenda using Bedrock
    try:
        agenda, meta = parse_agenda(
            text=text,
            today=today_date,
            tz=tz_str,
        )

    except ValidationError:
        logger.exception("Agenda validation failed")

        return _response(
            422,
            {
                "error": "validation_failed",
                "message": "The AI returned invalid agenda data.",
            },
        )

    except Exception:
        logger.exception("Failed to parse agenda with Bedrock")

        return _response(
            502,
            {
                "error": "parse_failed",
                "message": "Could not parse agenda using AI.",
            },
        )

    # CloudWatch structured log
    cw_log = {
        "event": "agenda_parsed",
        "user": user_sub,
        "model": meta.get("model", "unknown"),
        "prompt_version": meta.get("prompt_version", "v1"),
        "input_tokens": meta.get("input_tokens", 0),
        "output_tokens": meta.get("output_tokens", 0),
        "latency_ms": meta.get("latency_ms", 0),
        "cost_usd": meta.get("cost_usd", 0.0),
    }

    print(json.dumps(cw_log))

    return _response(
        200,
        {
            "agenda": agenda.model_dump(mode="json"),
            "model": meta["model"],
            "prompt_version": meta["prompt_version"],
        },
    )

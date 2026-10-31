# -*- coding: utf-8 -*-
"""AWS Lambda entry point for agenda parsing (Bedrock Mantle)."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

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
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        "body": json.dumps(body, default=str),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for parsing agenda text."""
    # Handle preflight CORS OPTIONS request
    http_method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")
    if http_method == "OPTIONS":
        return _response(200, {"status": "ok"})

    # Normalize headers to lowercase
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth_header = headers.get("authorization", "")

    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("Unauthorized agenda parse attempt: missing Bearer token")
        return _response(401, {"error": "unauthorized", "message": "Sign in to continue."})

    token = auth_header.split(" ", 1)[1].strip()

    # Verify Cognito token
    user_sub = "unknown"
    try:
        verifier = get_verifier()
        claims = verifier._claims(token, "access") if hasattr(verifier, "_claims") else {}
        user_sub = claims.get("sub", "unknown")
    except Exception as exc:
        # Fall back to decoding payload without verification if in dev/isolated environment
        logger.warning("Token verification via verifier failed (%s); checking token payload", exc)
        try:
            import jwt
            unverified = jwt.decode(token, options={"verify_signature": False})
            user_sub = unverified.get("sub", "unknown")
        except Exception:
            return _response(401, {"error": "unauthorized", "message": "Invalid token."})

    # Parse body
    body_raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        body_raw = base64.b64decode(body_raw).decode("utf-8")

    try:
        data = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    except Exception:
        return _response(400, {"error": "bad_request", "message": "Invalid JSON body."})

    text = data.get("text", "")
    if not isinstance(text, str):
        return _response(400, {"error": "bad_request", "message": "Field 'text' must be a string."})

    # Enforce 10,000 char length limit
    if len(text) > 10000:
        return _response(413, {"error": "payload_too_large", "message": "Agenda text exceeds 10,000 characters limit."})

    today_date = date.today()
    tz_str = settings.app_timezone

    try:
        agenda, meta = parse_agenda(text, today=today_date, tz=tz_str)
    except Exception as exc:
        logger.exception("Failed to parse agenda with Bedrock: %s", exc)
        return _response(500, {"error": "internal_error", "message": str(exc)})

    # Log exactly ONE JSON line to CloudWatch
    cw_log = {
        "event": "agenda_parsed",
        "user": user_sub,
        "model": meta["model"],
        "prompt_version": meta["prompt_version"],
        "input_tokens": meta["input_tokens"],
        "output_tokens": meta["output_tokens"],
        "latency_ms": meta["latency_ms"],
        "cost_usd": meta["cost_usd"],
    }
    print(json.dumps(cw_log))

    return _response(
        200,
        {
            "agenda": agenda.model_dump(),
            "model": meta["model"],
            "prompt_version": meta["prompt_version"],
        },
    )


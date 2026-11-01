
# -*- coding: utf-8 -*-
"""Simple connection test for Anthropic Claude on Amazon Bedrock."""

import os
import json
import logging

from anthropic import AnthropicBedrock

logging.basicConfig(level=logging.INFO)

DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"


def main() -> None:
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    model = os.getenv("PARSER_MODEL", DEFAULT_MODEL)

    print(f"AWS Region: {region}")
    print(f"Model: {model}")
    print("Connecting to Amazon Bedrock...")

    client = AnthropicBedrock(
        aws_region=region,
    )

    response = client.messages.create(
        model=model,
        max_tokens=100,
        temperature=0,
        system="You are a helpful assistant that replies with a short greeting.",
        messages=[
            {
                "role": "user",
                "content": "Say hello to the world!",
            }
        ],
    )

    out = {
        "response": response.content[0].text,
        "stop_reason": response.stop_reason,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

import os, json
from anthropic import AnthropicBedrock

def main() -> None:
    region = os.getenv("AWS_REGION", "us-east-1")
    model = os.getenv("PARSER_MODEL", "anthropic.claude-opus-5-5")
    client = AnthropicBedrock(region_name=region)
    response = client.messages.create(
        model=model,
        max_tokens=100,
        temperature=0,
        system="You are a helpful assistant that replies with a short greeting.",
        messages=[{"role": "user", "content": "Say hello to the world!"}],
    )
    out = {
        "response": response.content[0].text,
        "stop_reason": response.stop_reason,
        "usage": response.usage,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()


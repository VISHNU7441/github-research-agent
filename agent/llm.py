"""The chat model: gpt-oss-120b on Amazon Bedrock's mantle endpoint.

Mantle speaks the OpenAI API format, so LangChain's ChatOpenAI can talk to it.
We point it at Bedrock's URL and log in with a short-term Bedrock token made
from our normal AWS credentials (~/.aws), so there's no extra secret to store.
"""
from aws_bedrock_token_generator import provide_token
from langchain_openai import ChatOpenAI

from config import AWS_REGION, MANTLE_BASE_URL, MAX_OUTPUT_TOKENS, MODEL_ID, TEMPERATURE


def get_model() -> ChatOpenAI:
    """Create the chat model. Call it once per run: the token lasts up to 12 hours."""
    return ChatOpenAI(
        model=MODEL_ID,
        base_url=MANTLE_BASE_URL,                   # Bedrock, not openai.com
        api_key=provide_token(region=AWS_REGION),   # short-term token from your bedrock-dev keys
        temperature=TEMPERATURE,
        max_tokens=MAX_OUTPUT_TOKENS,
        max_retries=5,                              # retry throttling and network errors, with backoff
        timeout=120,                                # seconds
        use_responses_api=False,                    # use the Chat Completions API (tested with mantle)
    )


if __name__ == "__main__":
    model = get_model()
    reply = model.invoke("In one sentence: what is Amazon Bedrock?")
    print("=== Reply ===")
    print(reply.content)
    print("\n=== Tokens used ===")
    print(reply.usage_metadata)
    print("model:", reply.response_metadata.get("model_name"))

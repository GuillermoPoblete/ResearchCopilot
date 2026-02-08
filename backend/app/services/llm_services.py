import os
from openai import OpenAI

_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
print(f"[llm] OPENAI_API_KEY set: {bool(_OPENAI_API_KEY)}", flush=True)
client = OpenAI(api_key=_OPENAI_API_KEY)


def stream_chat_completion(messages):
    if not _OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not configured")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        stream=True,
    )

    for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content

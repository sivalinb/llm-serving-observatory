"""Read streaming Chat Completions without treating a chunk as one model token."""

import json
import os

import httpx
from opentelemetry.propagate import inject


async def sse_json(response):
    data = []
    async for line in response.aiter_lines():
        if line == "":
            if data:
                payload = "\n".join(data)
                data.clear()
                if payload == "[DONE]":
                    return
                yield json.loads(payload)
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data and "\n".join(data) != "[DONE]":
        yield json.loads("\n".join(data))


def normalize_usage(usage):
    """Unknown detail stays null. Cached/reasoning counts are subsets, not additions."""
    inputs = usage.get("prompt_tokens")
    outputs = usage.get("completion_tokens")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")

    def nonnegative(value):
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )

    inputs, outputs, cached, reasoning = map(nonnegative, (inputs, outputs, cached, reasoning))
    if cached is not None and inputs is not None and cached > inputs:
        cached = None
    if reasoning is not None and outputs is not None and reasoning > outputs:
        reasoning = None
    return {
        "input": inputs,
        "output": outputs,
        "cached_input": cached,
        "uncached_input": inputs - cached if inputs is not None and cached is not None else None,
        "reasoning": reasoning,
        "visible_output": outputs - reasoning
        if outputs is not None and reasoning is not None
        else None,
        "total": inputs + outputs if inputs is not None and outputs is not None else None,
    }


async def stream_upstream(req, record, client, messages=None, temperature=0):
    url = os.environ["UPSTREAM_URL"].rstrip("/") + "/chat/completions"
    headers = {}
    if os.getenv("UPSTREAM_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["UPSTREAM_API_KEY"]
    inject(headers)
    body = {
        "model": os.environ["UPSTREAM_MODEL"],
        "messages": messages or [{"role": "user", "content": req.prompt}],
        "max_tokens": req.output_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    saw_finish = False
    async with client.stream("POST", url, json=body, headers=headers) as response:
        if response.status_code >= 400:
            # Provider bodies can echo prompts or secrets; do not persist them.
            raise httpx.HTTPStatusError(
                f"Upstream HTTP {response.status_code}", request=response.request, response=response
            )
        async for event in sse_json(response):
            if "error" in event:
                raise RuntimeError("Upstream returned an error event")
            if event.get("usage"):
                record["tokens"] = normalize_usage(event["usage"])
                record["token_provenance"] = "provider_reported"
            for choice in event.get("choices", []):
                if choice.get("finish_reason"):
                    record["finish_reason"] = choice["finish_reason"]
                    saw_finish = True
                content = choice.get("delta", {}).get("content")
                if isinstance(content, str) and content:
                    yield content
    if not saw_finish:
        raise RuntimeError("Upstream stream ended without a finish reason")

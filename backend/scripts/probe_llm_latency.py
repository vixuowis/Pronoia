#!/usr/bin/env python3
"""Minimal latency probe for the configured LLM endpoint."""

import asyncio
import time

import httpx
from openai import AsyncOpenAI

from app import config


async def main() -> None:
    direct_started = time.monotonic()
    try:
        transport = httpx.AsyncHTTPTransport(
            local_address="0.0.0.0",
            retries=0,
        )
        async with httpx.AsyncClient(timeout=15, transport=transport) as direct:
            response = await asyncio.wait_for(
                direct.post(
                    f"{config.LLM_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                    json={
                        "model": config.LLM_MODEL,
                        "messages": [{"role": "user", "content": "Reply with OK only."}],
                        "max_tokens": 4,
                    },
                ),
                timeout=20,
            )
        print(
            f"direct status={response.status_code} seconds={time.monotonic() - direct_started:.2f} "
            f"body={response.text[:200]!r}"
        )
    except Exception as exc:
        print(
            f"direct_error seconds={time.monotonic() - direct_started:.2f} "
            f"type={type(exc).__name__} detail={str(exc)[:200]}"
        )

    sdk_http = httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=0),
        timeout=20,
    )
    client = AsyncOpenAI(
        base_url=config.LLM_BASE_URL,
        api_key=config.LLM_API_KEY,
        timeout=20,
        http_client=sdk_http,
    )
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "user", "content": "Reply with OK only."}],
                max_tokens=4,
            ),
            timeout=25,
        )
        content = (response.choices[0].message.content or "")[:20]
        print(f"ok seconds={time.monotonic() - started:.2f} content={content!r}")
    except Exception as exc:
        print(
            f"error seconds={time.monotonic() - started:.2f} "
            f"type={type(exc).__name__} detail={str(exc)[:200]}"
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

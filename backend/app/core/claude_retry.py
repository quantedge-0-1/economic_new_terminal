"""
Exponential backoff retry wrapper for Claude API calls.

Retries on 529 (overloaded), 5xx server errors, connection errors, and timeouts.
Raises immediately on 4xx (auth failure, bad request) — those won't fix on retry.
"""

import asyncio

import anthropic

_MAX_ATTEMPTS = 4  # 1 initial + 3 retries
_DELAYS = (2, 4, 8)  # seconds between attempts


async def claude_with_retry(client: anthropic.AsyncAnthropic, **kwargs):
    """
    Drop-in replacement for client.messages.create() with retry logic.
    Raises the last exception when all attempts are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            if exc.status_code in (529, 500, 502, 503, 504):
                last_exc = exc
            else:
                raise  # 4xx — retrying won't help
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as exc:
            last_exc = exc

        if attempt < len(_DELAYS):
            await asyncio.sleep(_DELAYS[attempt])

    raise last_exc  # type: ignore[misc]

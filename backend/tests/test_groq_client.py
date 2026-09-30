"""Groq HTTP client: retries, optional-parameter fallback, error mapping and JSON parsing."""

import json

import httpx
import pytest

from app.groq import client as groq
from app.groq.client import GroqError, chat_json

pytestmark = pytest.mark.anyio


def _reply(content: str, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}, headers=headers)


@pytest.fixture
def transport(services):
    replies: list[httpx.Response | Exception] = []
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    groq.set_transport(httpx.MockTransport(handler))
    return replies, bodies


async def test_parses_json_and_reports_token_usage(transport):
    replies, bodies = transport
    replies.append(_reply('```json\n{"a": 1}\n```'))
    result = await chat_json("sys", "user")
    assert result.data == {"a": 1}
    assert (result.prompt_tokens, result.completion_tokens) == (11, 7)
    assert bodies[0]["response_format"] == {"type": "json_object"}


async def test_rate_limit_is_retried_after_short_wait(transport):
    replies, _ = transport
    replies += [httpx.Response(429, headers={"retry-after": "0"}), _reply('{"ok": true}')]
    assert (await chat_json("s", "u")).data == {"ok": True}


async def test_long_rate_limit_is_reported_not_waited(transport):
    replies, _ = transport
    replies.append(httpx.Response(429, headers={"retry-after": "120"}))
    with pytest.raises(GroqError) as err:
        await chat_json("s", "u")
    assert err.value.status_code == 429


async def test_unsupported_optional_param_is_dropped(transport):
    replies, bodies = transport
    replies += [httpx.Response(400, text="reasoning_effort is not supported"), _reply('{"x": 1}')]
    await chat_json("s", "u", reasoning_effort="low")
    assert "reasoning_effort" in bodies[0] and "reasoning_effort" not in bodies[1]


async def test_reasoning_effort_only_sent_to_supporting_models(transport, monkeypatch):
    from app.config import get_settings

    replies, bodies = transport
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    get_settings.cache_clear()
    replies.append(_reply('{"x": 1}'))
    await chat_json("s", "u", reasoning_effort="low")
    assert "reasoning_effort" not in bodies[0]


@pytest.mark.parametrize(
    ("reply", "status", "retryable"),
    [
        (httpx.ReadTimeout("t"), 504, False),
        (httpx.ConnectError("c"), 503, False),
        (httpx.Response(401, json={"error": {"message": "bad key"}}), 502, False),
        (httpx.Response(500, text="boom"), 502, False),
        (_reply("no json here"), 502, True),
        (_reply("[1, 2]"), 502, True),
        (_reply(""), 502, True),
        (httpx.Response(200, json={"unexpected": True}), 502, True),
    ],
)
async def test_errors_are_mapped(transport, reply, status, retryable):
    replies, _ = transport
    replies.append(reply)
    with pytest.raises(GroqError) as err:
        await chat_json("s", "u")
    assert err.value.status_code == status and err.value.retryable is retryable


async def test_upstream_error_body_is_not_forwarded(transport):
    replies, _ = transport
    replies.append(httpx.Response(500, json={"error": {"message": "internal trace id 123 at host secret-node"}}))
    with pytest.raises(GroqError) as err:
        await chat_json("s", "u")
    assert "secret-node" not in str(err.value)


async def test_one_connection_pool_is_reused(services):
    first = groq._client()
    assert groq._client() is first

"""Groq chat-completions client (JSON mode).

One pooled httpx.AsyncClient is reused for every call (no TLS handshake per request). Upstream
error bodies are logged, never forwarded to API clients.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# On 429, wait for Groq's retry-after (if short) and retry, instead of failing the request.
MAX_RATE_LIMIT_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 15.0
# Request parameters that some models reject with HTTP 400; dropped and retried once if so.
OPTIONAL_PARAMS = ("response_format", "reasoning_effort")


class GroqError(Exception):
    """A user-safe error message plus the HTTP status the API should return.

    retryable=True marks malformed model output, where one more attempt can succeed.
    """

    def __init__(self, message: str, status_code: int = 502, *, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class ChatResult:
    data: dict[str, Any]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


_http: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=get_settings().groq_timeout_seconds)
    return _http


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Test hook: route Groq traffic through a mock transport (None restores the default)."""
    global _http
    _http = httpx.AsyncClient(transport=transport, timeout=get_settings().groq_timeout_seconds) if transport else None


async def aclose() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


def _supports_reasoning_effort(model: str) -> bool:
    return "gpt-oss" in model or model.startswith("qwen/")


async def chat_json(system: str, user: str, *, reasoning_effort: str | None = None) -> ChatResult:
    """Call Groq in JSON mode and return the parsed JSON object and token usage."""
    s = get_settings()
    if not s.groq_api_key:
        raise GroqError("GROQ_API_KEY is not configured on the server.", 503)

    body: dict[str, Any] = {
        "model": s.groq_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if reasoning_effort and _supports_reasoning_effort(s.groq_model):
        body["reasoning_effort"] = reasoning_effort
    headers = {"Authorization": f"Bearer {s.groq_api_key}"}

    try:
        resp = await _post(body, headers)
    except httpx.TimeoutException as exc:
        raise GroqError(f"Groq request timed out after {s.groq_timeout_seconds:.0f}s.", 504) from exc
    except httpx.HTTPError as exc:
        raise GroqError(f"Groq is unavailable ({type(exc).__name__}).", 503) from exc

    if resp.status_code == 429:
        retry = resp.headers.get("retry-after")
        raise GroqError(f"Groq rate limit reached{f', retry after {retry}s' if retry else ''}.", 429)
    if resp.status_code in (401, 403):
        raise GroqError("Groq authentication failed - check the server's GROQ_API_KEY.", 502)
    if resp.status_code >= 400:
        log.warning("Groq API error %s: %s", resp.status_code, _error_message(resp))
        raise GroqError(f"Groq API error (HTTP {resp.status_code}).", 502)

    try:
        payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise GroqError("Groq returned an unexpected response shape.", retryable=True) from exc
    usage = payload.get("usage") or {}
    return ChatResult(_parse_json(content), usage.get("prompt_tokens"), usage.get("completion_tokens"))


async def _post(body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    http = _client()
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        resp = await http.post(GROQ_URL, json=body, headers=headers)
        rejected = _rejected_param(resp, body)
        if rejected:
            # The model does not support this optional parameter: drop it and retry once.
            log.info("Groq model rejected '%s'; retrying without it", rejected)
            body.pop(rejected)
            resp = await http.post(GROQ_URL, json=body, headers=headers)
        wait = _retry_after(resp)
        if resp.status_code != 429 or wait is None or attempt == MAX_RATE_LIMIT_RETRIES:
            return resp
        log.info("Groq rate limited; retrying in %.1fs", wait)
        await asyncio.sleep(wait)
    return resp  # pragma: no cover - loop always returns


def _rejected_param(resp: httpx.Response, body: dict[str, Any]) -> str | None:
    if resp.status_code != 400:
        return None
    text = resp.text
    return next((p for p in OPTIONAL_PARAMS if p in body and p in text), None)


def _retry_after(resp: httpx.Response) -> float | None:
    """Seconds to wait before retrying a 429, if Groq says and it's short enough to wait for."""
    try:
        wait = float(resp.headers.get("retry-after", ""))
    except ValueError:
        return None
    return wait if 0 <= wait <= MAX_RETRY_WAIT_SECONDS else None


def _error_message(resp: httpx.Response) -> str:
    try:
        return str(resp.json()["error"]["message"])[:300]
    except Exception:  # noqa: BLE001
        return resp.text[:300]


def _parse_json(content: str | None) -> dict[str, Any]:
    if not content:
        raise GroqError("Groq returned an empty response.", retryable=True)
    text = content.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise GroqError("Groq response did not contain JSON.", retryable=True)
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GroqError("Groq returned invalid JSON.", retryable=True) from exc
    if not isinstance(data, dict):
        raise GroqError("Groq returned JSON that is not an object.", retryable=True)
    return data

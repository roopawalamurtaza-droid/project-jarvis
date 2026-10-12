"""Bounded HTTP text adapters. Provider output never executes an action.

The adapters deliberately do not offer provider tools, browse, upload files, retry,
or fall back to another provider. Cloud consent is enforced by the service/factory.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class CancelSignal(Protocol):
    def is_set(self) -> bool: ...


class ProviderError(RuntimeError):
    """A safe, user-facing failure containing no response body or credentials."""

    def __init__(self, message: str, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


class ProviderCancelled(ProviderError):
    def __init__(self) -> None:
        super().__init__("The response was cancelled.", "cancelled")


@dataclass(frozen=True)
class ProviderReply:
    text: str
    usage: dict[str, int | None]
    truncated: bool = False


class TextProvider(Protocol):
    name: str

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float,
        max_output_tokens: int,
        cancel: CancelSignal | None = None,
    ) -> ProviderReply: ...


def _usage(input_tokens: Any, output_tokens: Any, total_tokens: Any = None) -> dict:
    def count(value: Any) -> int | None:
        return (
            value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        )

    input_count, output_count, total_count = map(count, (input_tokens, output_tokens, total_tokens))
    if total_count is None and input_count is not None and output_count is not None:
        total_count = input_count + output_count
    return {"input_tokens": input_count, "output_tokens": output_count, "total_tokens": total_count}


class HTTPProvider:
    name = "http"

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float,
        max_output_tokens: int,
        cancel: CancelSignal | None = None,
    ) -> ProviderReply:
        if cancel is not None and cancel.is_set():
            raise ProviderCancelled()
        if not model or len(model) > 256 or any(ord(char) < 32 for char in model):
            raise ProviderError("Choose a valid model name in Settings.", "invalid_model")
        if not 0 < timeout <= 300 or not 16 <= max_output_tokens <= 32768:
            raise ProviderError("The request limits are invalid.", "invalid_limits")
        url, payload, headers = self._build(messages, model, max_output_tokens)
        # Desktop and API run this synchronous entry point on workers. Cancellation
        # cancels the async HTTP operation and closes its connection, not just a UI flag.
        try:
            return asyncio.run(self._run(url, payload, headers, timeout, cancel))
        except ProviderError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise ProviderError(
                "The provider timed out. Try again when it is available.", "timeout"
            ) from None
        except httpx.HTTPError:
            raise ProviderError(
                "Could not reach the selected provider.", "connection_error"
            ) from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError(
                "The provider returned an unexpected response.", "invalid_response"
            ) from None

    async def _run(self, url, payload, headers, timeout, cancel) -> ProviderReply:
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            request = asyncio.create_task(self._post(client, url, payload, headers))
            deadline = asyncio.get_running_loop().time() + timeout
            try:
                while not request.done():
                    if cancel is not None and cancel.is_set():
                        raise ProviderCancelled()
                    if asyncio.get_running_loop().time() >= deadline:
                        raise ProviderError(
                            "The provider timed out. Try again when it is available.", "timeout"
                        )
                    await asyncio.wait({request}, timeout=0.05)
                if cancel is not None and cancel.is_set():
                    raise ProviderCancelled()
                return self._parse(request.result())
            finally:
                if not request.done():
                    request.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await request

    async def _post(self, client, url, payload, headers) -> dict:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code >= 300:
                # Never expose the body, URL, request, key, or server-generated error.
                status = response.status_code
                if status in (401, 403):
                    message, code = "The provider rejected the API key or access.", "authentication"
                elif status == 429:
                    message, code = "The provider request limit was reached.", "rate_limit"
                elif status == 404:
                    message, code = (
                        "The provider or model was not found. Check Settings.",
                        "not_found",
                    )
                else:
                    message, code = (
                        f"The provider could not complete the request (HTTP {status}).",
                        "http_error",
                    )
                raise ProviderError(message, code)
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ProviderError(
                        "The provider response exceeded the size limit.", "response_too_large"
                    )
            result = json.loads(data)
            if not isinstance(result, dict):
                raise ProviderError(
                    "The provider returned an unexpected response.", "invalid_response"
                )
            return result

    def _build(self, messages, model, max_output_tokens):
        raise NotImplementedError

    def _parse(self, data):
        raise NotImplementedError

    @staticmethod
    def _text(text: Any) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(
                "The provider returned no text. The response may have been blocked.",
                "empty_response",
            )
        return text


class OllamaProvider(HTTPProvider):
    name = "ollama"

    def __init__(self, url: str = "http://127.0.0.1:11434", **kwargs) -> None:
        super().__init__(**kwargs)
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ProviderError(
                "Ollama must use a loopback URL without credentials.", "invalid_endpoint"
            )
        try:
            _ = parsed.port
        except ValueError:
            raise ProviderError(
                "The Ollama endpoint port is invalid.", "invalid_endpoint"
            ) from None
        self._url = url.rstrip("/")

    def _build(self, messages, model, max_output_tokens):
        return (
            f"{self._url}/api/chat",
            {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"num_predict": max_output_tokens},
            },
            {},
        )

    def _parse(self, data):
        if data.get("error"):
            raise ProviderError("Ollama could not generate a response. Check the installed model.")
        return ProviderReply(
            self._text(data.get("message", {}).get("content")),
            _usage(data.get("prompt_eval_count"), data.get("eval_count")),
            data.get("done_reason") == "length",
        )


class OpenAIProvider(HTTPProvider):
    name = "openai"

    def __init__(self, api_key: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._key = api_key

    def _build(self, messages, model, max_output_tokens):
        return (
            "https://api.openai.com/v1/responses",
            {
                "model": model,
                "input": messages,
                "max_output_tokens": max_output_tokens,
                "store": False,
            },
            {"Authorization": f"Bearer {self._key}"},
        )

    def _parse(self, data):
        if data.get("error") or data.get("status") in ("failed", "cancelled"):
            raise ProviderError("OpenAI could not complete the response.")
        chunks = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        chunks.append(self._text(content.get("text")))
                    elif content.get("type") == "refusal":
                        chunks.append(self._text(content.get("refusal")))
        usage = data.get("usage") or {}
        return ProviderReply(
            self._text("\n".join(chunks)),
            _usage(
                usage.get("input_tokens"), usage.get("output_tokens"), usage.get("total_tokens")
            ),
            data.get("status") == "incomplete",
        )


class GeminiProvider(HTTPProvider):
    name = "gemini"

    def __init__(self, api_key: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._key = api_key

    def _build(self, messages, model, max_output_tokens):
        system = "\n\n".join(item["content"] for item in messages if item["role"] == "system")
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages
            if item["role"] != "system"
        ]
        payload = {"contents": contents, "generationConfig": {"maxOutputTokens": max_output_tokens}}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
            payload,
            {"x-goog-api-key": self._key},
        )

    def _parse(self, data):
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError(
                "Gemini returned no text. The response may have been blocked.", "empty_response"
            )
        candidate = candidates[0]
        text = "\n".join(
            part["text"]
            for part in candidate.get("content", {}).get("parts", [])
            if isinstance(part.get("text"), str) and not part.get("thought", False)
        )
        usage = data.get("usageMetadata") or {}
        return ProviderReply(
            self._text(text),
            _usage(
                usage.get("promptTokenCount"),
                usage.get("candidatesTokenCount"),
                usage.get("totalTokenCount"),
            ),
            candidate.get("finishReason") == "MAX_TOKENS",
        )


def create_provider(settings, secret_store=None) -> TextProvider:
    """Resolve exactly the selected provider; secrets never cross to another one."""
    if settings.provider == "ollama":
        return OllamaProvider(settings.ollama_url)
    if settings.provider not in ("openai", "gemini"):
        raise ProviderError("Choose a supported provider in Settings.", "invalid_provider")
    if not settings.cloud_allowed:
        raise ProviderError(
            "Cloud chat is disabled. Enable cloud consent in Settings first.", "cloud_consent"
        )
    key_name = "OPENAI_API_KEY" if settings.provider == "openai" else "GEMINI_API_KEY"
    key = secret_store.get(key_name) if secret_store is not None else None
    if not key or not key.strip():
        raise ProviderError(
            f"Add the {settings.provider} API key in Settings first.", "missing_key"
        )
    return OpenAIProvider(key) if settings.provider == "openai" else GeminiProvider(key)

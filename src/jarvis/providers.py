"""Bounded HTTP adapters. Provider output never executes an action.

Function schemas are sent only when explicitly supplied by the caller. Returned
calls are untrusted proposals; authorization and execution belong to the local
task engine. These adapters never browse, upload files, retry, or switch providers.
Cloud consent is enforced by the service/factory.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.parse import quote, urlsplit

import httpx

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TOOL_CALLS = 6
MAX_TOOL_SCHEMAS = 64
MAX_TOOL_SCHEMA_BYTES = 256 * 1024
MAX_TOOL_ARGUMENT_BYTES = 64 * 1024
MAX_STREAM_TEXT_CHARS = 100000
_TOOL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


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
class ProviderToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass(frozen=True)
class ProviderReply:
    text: str
    usage: dict[str, int | None]
    truncated: bool = False
    tool_calls: tuple[ProviderToolCall, ...] = ()


class TextProvider(Protocol):
    name: str

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float,
        max_output_tokens: int,
        tools: list[dict[str, Any]] | None = None,
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


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate JSON property")
        result[name] = value
    return result


def _invalid_constant(_):
    raise ValueError("Non-finite JSON number")


def _load_json(raw):
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)


def _bounded_json(value, limit: int):
    """Reject non-JSON values and bound nesting before serialization or copying."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 16 or count > 8192:
            raise ValueError("JSON complexity limit")
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("JSON property names must be strings")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Non-finite JSON number")
        elif item is not None and not isinstance(item, (str, int, bool)):
            raise ValueError("JSON value required")
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    if len(encoded) > limit:
        raise ValueError("JSON size limit")
    return _load_json(encoded)


def _normalize_tools(tools):
    if tools is None:
        return []
    try:
        if not isinstance(tools, list) or len(tools) > MAX_TOOL_SCHEMAS:
            raise ValueError("Invalid tool list")
        normalized = []
        names = set()
        for tool in tools:
            if not isinstance(tool, dict) or set(tool) != {"name", "description", "parameters"}:
                raise ValueError("Invalid function definition")
            name, description, parameters = tool["name"], tool["description"], tool["parameters"]
            if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name) or name in names:
                raise ValueError("Invalid or duplicate function name")
            if not isinstance(description, str) or not 0 < len(description) <= 4096:
                raise ValueError("Invalid function description")
            if not isinstance(parameters, dict) or parameters.get("type") != "object":
                raise ValueError("Function parameters must describe an object")
            names.add(name)
            normalized.append({"name": name, "description": description, "parameters": parameters})
        return _bounded_json(normalized, MAX_TOOL_SCHEMA_BYTES)
    except (ValueError, TypeError, RecursionError):
        raise ProviderError("The supplied tool definitions are invalid.", "invalid_tools") from None


def _tool_call(name, arguments, identifier, allowed_tools, *, encoded=False):
    try:
        if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name) or name not in allowed_tools:
            raise ValueError("Unregistered function name")
        if (
            not isinstance(identifier, str)
            or len(identifier) > 256
            or any(ord(char) < 32 for char in identifier)
        ):
            raise ValueError("Invalid function identifier")
        if encoded:
            if (
                not isinstance(arguments, str)
                or len(arguments.encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES
            ):
                raise ValueError("Invalid encoded arguments")
            arguments = _load_json(arguments)
        if not isinstance(arguments, dict):
            raise ValueError("Function arguments must be an object")
        arguments = _bounded_json(arguments, MAX_TOOL_ARGUMENT_BYTES)
        return ProviderToolCall(name, arguments, identifier)
    except (ValueError, TypeError, RecursionError):
        raise ProviderError(
            "The provider returned an invalid or unregistered tool request.", "invalid_tool_call"
        ) from None


def _call_list(calls):
    if not isinstance(calls, list) or len(calls) > MAX_TOOL_CALLS:
        raise ProviderError(
            "The provider returned an invalid tool request list.", "invalid_tool_call"
        )
    return calls


def _finish_calls(calls):
    identifiers = [call.id for call in calls if call.id]
    if len(identifiers) != len(set(identifiers)):
        raise ProviderError(
            "The provider returned duplicate tool identifiers.", "invalid_tool_call"
        )
    return tuple(calls)


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
        tools: list[dict[str, Any]] | None = None,
        cancel: CancelSignal | None = None,
    ) -> ProviderReply:
        if cancel is not None and cancel.is_set():
            raise ProviderCancelled()
        if not model or len(model) > 256 or any(ord(char) < 32 for char in model):
            raise ProviderError("Choose a valid model name in Settings.", "invalid_model")
        if not 0 < timeout <= 300 or not 16 <= max_output_tokens <= 32768:
            raise ProviderError("The request limits are invalid.", "invalid_limits")
        definitions = _normalize_tools(tools)
        url, payload, headers = self._build(messages, model, max_output_tokens, definitions)
        # Desktop and API run this synchronous entry point on workers. Cancellation
        # cancels the async HTTP operation and closes its connection, not just a UI flag.
        try:
            return asyncio.run(
                self._run(
                    url,
                    payload,
                    headers,
                    timeout,
                    cancel,
                    frozenset(tool["name"] for tool in definitions),
                )
            )
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
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise ProviderError(
                "The provider returned an unexpected response.", "invalid_response"
            ) from None

    async def _run(
        self, url, payload, headers, timeout, cancel, allowed_tools, on_delta=None
    ) -> ProviderReply:
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            request = asyncio.create_task(
                self._post(client, url, payload, headers)
                if on_delta is None
                else self._post_stream(client, url, payload, headers, on_delta, cancel)
            )
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
                result = request.result()
                return (
                    self._parse(result, allowed_tools=allowed_tools) if on_delta is None else result
                )
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
            result = _load_json(data)
            if not isinstance(result, dict):
                raise ProviderError(
                    "The provider returned an unexpected response.", "invalid_response"
                )
            return result

    def _build(self, messages, model, max_output_tokens, tools):
        raise NotImplementedError

    def _parse(self, data, *, allowed_tools=frozenset()):
        raise NotImplementedError

    @staticmethod
    def _text(text: Any) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(
                "The provider returned no text. The response may have been blocked.",
                "empty_response",
            )
        return text

    @classmethod
    def _reply_text(cls, text, calls):
        if calls and (text is None or isinstance(text, str) and not text.strip()):
            return ""
        return cls._text(text)


class _AnswerDeltas:
    """Hide legacy inline thinking tags even when split between network chunks.

    Modern Ollama sends reasoning in message.thinking. A few older models embed
    a leading <think> block in content; retain only a possible boundary prefix
    and never publish that block. Once the answer starts, literal tags in prose
    or code are preserved rather than mistaken for hidden model reasoning.
    """

    def __init__(self):
        self.pending = ""
        self.hidden = False
        self.answer_started = False

    def feed(self, content: str) -> str:
        if self.answer_started:
            remaining, self.pending = self.pending + content, ""
            return remaining
        self.pending += content
        output = []
        while self.pending:
            marker = "</think>" if self.hidden else "<think>"
            position = self.pending.lower().find(marker)
            if position >= 0:
                if not self.hidden:
                    if self.pending[:position].strip():
                        self.answer_started = True
                        output.append(self.pending)
                        self.pending = ""
                        break
                    output.append(self.pending[:position])
                self.pending = self.pending[position + len(marker) :]
                self.hidden = not self.hidden
                continue
            keep = 0
            lowered = self.pending.lower()
            for length in range(1, min(len(marker), len(lowered) + 1)):
                if lowered.endswith(marker[:length]):
                    keep = length
            ready = self.pending[:-keep] if keep else self.pending
            if not self.hidden:
                output.append(ready)
                if ready.strip():
                    self.answer_started = True
                    if keep:
                        output.append(self.pending[-keep:])
                    self.pending = ""
                    break
            self.pending = self.pending[-keep:] if keep else ""
            break
        return "".join(output)

    def finish(self) -> str:
        if self.hidden:
            raise ProviderError(
                "Ollama's response ended inside an incomplete thinking block.", "invalid_response"
            )
        remaining, self.pending = self.pending, ""
        return remaining


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

    def generate_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str,
        timeout: float,
        max_output_tokens: int,
        on_delta: Callable[[str], None],
        cancel: CancelSignal | None = None,
    ) -> ProviderReply:
        """Stream validated ordinary text on the calling worker, then return its receipt.

        Ollama's NDJSON content is streamed as received, never a simulated typing
        effect. Separate thinking fields are ignored. No function schemas are sent
        and unsolicited tool proposals are rejected. Consumers must discard their
        draft on failure; partial content never becomes a saved completed answer.
        """
        if cancel is not None and cancel.is_set():
            raise ProviderCancelled()
        if not callable(on_delta):
            raise ProviderError("A valid streaming receiver is required.", "invalid_callback")
        if not model or len(model) > 256 or any(ord(char) < 32 for char in model):
            raise ProviderError("Choose a valid model name in Settings.", "invalid_model")
        if not 0 < timeout <= 300 or not 16 <= max_output_tokens <= 32768:
            raise ProviderError("The request limits are invalid.", "invalid_limits")
        url, payload, headers = self._build(messages, model, max_output_tokens, [])
        payload["stream"] = True
        try:
            return asyncio.run(
                self._run(url, payload, headers, timeout, cancel, frozenset(), on_delta)
            )
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
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise ProviderError(
                "The provider returned an unexpected response.", "invalid_response"
            ) from None

    async def _post_stream(self, client, url, payload, headers, on_delta, cancel) -> ProviderReply:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code >= 300:
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
            pending = bytearray()
            size = 0
            text_size = 0
            pieces = []
            terminal = None
            answer = _AnswerDeltas()

            def publish(delta):
                nonlocal text_size
                if not delta:
                    return
                if cancel is not None and cancel.is_set():
                    raise ProviderCancelled()
                text_size += len(delta)
                if text_size > MAX_STREAM_TEXT_CHARS:
                    raise ProviderError(
                        "The provider text exceeded the application size limit.",
                        "response_too_large",
                    )
                pieces.append(delta)
                try:
                    on_delta(delta)
                except ProviderError:
                    raise
                except Exception:
                    raise ProviderError(
                        "The response display could not receive streamed text.",
                        "stream_receiver_error",
                    ) from None
                if cancel is not None and cancel.is_set():
                    raise ProviderCancelled()

            def consume(line):
                nonlocal terminal
                if not line.strip():
                    return
                if terminal is not None:
                    raise ProviderError(
                        "Ollama returned data after completing its response.", "invalid_response"
                    )
                data = _load_json(line)
                if not isinstance(data, dict):
                    raise ProviderError("Ollama returned an invalid stream.", "invalid_response")
                # Enforce the same JSON depth/type safety as structured tool data.
                _bounded_json(data, MAX_RESPONSE_BYTES)
                if data.get("error"):
                    raise ProviderError(
                        "Ollama could not generate a response. Check the installed model."
                    )
                done = data.get("done")
                message = data.get("message")
                if not isinstance(done, bool) or not isinstance(message, dict):
                    raise ProviderError("Ollama returned an invalid stream.", "invalid_response")
                if message.get("role") not in (None, "assistant"):
                    raise ProviderError("Ollama returned an invalid stream.", "invalid_response")
                calls = _call_list(message.get("tool_calls", []))
                if calls:
                    raise ProviderError(
                        "Ollama returned an unsolicited tool request.", "invalid_tool_call"
                    )
                content = message.get("content", "")
                if not isinstance(content, str):
                    raise ProviderError("Ollama returned an invalid stream.", "invalid_response")
                # Only content enters the answer; message.thinking is never emitted.
                publish(answer.feed(content))
                if done:
                    publish(answer.finish())
                    terminal = data

            async for chunk in response.aiter_bytes():
                if cancel is not None and cancel.is_set():
                    raise ProviderCancelled()
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ProviderError(
                        "The provider response exceeded the size limit.", "response_too_large"
                    )
                pending.extend(chunk)
                while (end := pending.find(b"\n")) >= 0:
                    line = bytes(pending[:end])
                    del pending[: end + 1]
                    consume(line)
            if pending.strip():
                consume(bytes(pending))
            if terminal is None:
                raise ProviderError(
                    "Ollama's response ended before completion.", "incomplete_response"
                )
            return ProviderReply(
                self._text("".join(pieces)),
                _usage(terminal.get("prompt_eval_count"), terminal.get("eval_count")),
                terminal.get("done_reason") == "length",
            )

    def _build(self, messages, model, max_output_tokens, tools):
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": max_output_tokens},
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": tool} for tool in tools]
        return (
            f"{self._url}/api/chat",
            payload,
            {},
        )

    def _parse(self, data, *, allowed_tools=frozenset()):
        if data.get("error"):
            raise ProviderError("Ollama could not generate a response. Check the installed model.")
        message = data.get("message", {})
        calls = []
        for item in _call_list(message.get("tool_calls", [])):
            if not isinstance(item, dict) or item.get("type", "function") != "function":
                raise ProviderError("Ollama returned an invalid tool request.", "invalid_tool_call")
            function = item.get("function")
            if not isinstance(function, dict):
                raise ProviderError("Ollama returned an invalid tool request.", "invalid_tool_call")
            calls.append(
                _tool_call(
                    function.get("name"),
                    function.get("arguments"),
                    item.get("id", ""),
                    allowed_tools,
                )
            )
        calls = _finish_calls(calls)
        return ProviderReply(
            self._reply_text(message.get("content"), calls),
            _usage(data.get("prompt_eval_count"), data.get("eval_count")),
            data.get("done_reason") == "length",
            calls,
        )


class OpenAIProvider(HTTPProvider):
    name = "openai"

    def __init__(self, api_key: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._key = api_key

    def _build(self, messages, model, max_output_tokens, tools):
        payload = {
            "model": model,
            "input": messages,
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        if tools:
            # Keep optional/default fields exactly as specified. The local task
            # engine validates the complete schema before proposing any action.
            payload["tools"] = [{"type": "function", **tool, "strict": False} for tool in tools]
        return (
            "https://api.openai.com/v1/responses",
            payload,
            {"Authorization": f"Bearer {self._key}"},
        )

    def _parse(self, data, *, allowed_tools=frozenset()):
        if data.get("error") or data.get("status") in ("failed", "cancelled"):
            raise ProviderError("OpenAI could not complete the response.")
        chunks, calls = [], []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        chunks.append(self._text(content.get("text")))
                    elif content.get("type") == "refusal":
                        chunks.append(self._text(content.get("refusal")))
            elif item.get("type") == "function_call":
                if item.get("status") not in (None, "completed") or len(calls) >= MAX_TOOL_CALLS:
                    raise ProviderError(
                        "OpenAI returned an invalid tool request.", "invalid_tool_call"
                    )
                calls.append(
                    _tool_call(
                        item.get("name"),
                        item.get("arguments"),
                        item.get("call_id", ""),
                        allowed_tools,
                        encoded=True,
                    )
                )
        calls = _finish_calls(calls)
        usage = data.get("usage") or {}
        return ProviderReply(
            self._reply_text("\n".join(chunks), calls),
            _usage(
                usage.get("input_tokens"), usage.get("output_tokens"), usage.get("total_tokens")
            ),
            data.get("status") == "incomplete",
            calls,
        )


class GeminiProvider(HTTPProvider):
    name = "gemini"

    def __init__(self, api_key: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._key = api_key

    def _build(self, messages, model, max_output_tokens, tools):
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
        if tools:
            # Gemini's JSON Schema field accepts Pydantic schema constraints;
            # its alternative OpenAPI Schema field supports a different subset.
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parametersJsonSchema": tool["parameters"],
                        }
                        for tool in tools
                    ]
                }
            ]
        return (
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
            payload,
            {"x-goog-api-key": self._key},
        )

    def _parse(self, data, *, allowed_tools=frozenset()):
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError(
                "Gemini returned no text. The response may have been blocked.", "empty_response"
            )
        candidate = candidates[0]
        chunks, calls = [], []
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("thought", False):
                continue
            if isinstance(part.get("text"), str) and part["text"].strip():
                chunks.append(part["text"])
            if "functionCall" in part:
                function = part["functionCall"]
                if not isinstance(function, dict) or len(calls) >= MAX_TOOL_CALLS:
                    raise ProviderError(
                        "Gemini returned an invalid tool request.", "invalid_tool_call"
                    )
                calls.append(
                    _tool_call(
                        function.get("name"),
                        function.get("args"),
                        function.get("id", ""),
                        allowed_tools,
                    )
                )
        calls = _finish_calls(calls)
        usage = data.get("usageMetadata") or {}
        return ProviderReply(
            self._reply_text("\n".join(chunks), calls),
            _usage(
                usage.get("promptTokenCount"),
                usage.get("candidatesTokenCount"),
                usage.get("totalTokenCount"),
            ),
            candidate.get("finishReason") == "MAX_TOKENS",
            calls,
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

import asyncio
import json
import threading
import time

import httpx
import pytest

from jarvis.config import Settings
from jarvis.providers import (
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderCancelled,
    ProviderError,
    create_provider,
)

MESSAGES = [
    {"role": "system", "content": "Be helpful."},
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi"},
    {"role": "user", "content": "How are you?"},
]


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
def test_adapters_send_documented_payload_and_normalize_usage(kind):
    captured = []

    def handle(request):
        captured.append(request)
        if kind == "ollama":
            response = {"message": {"content": "hello"}, "prompt_eval_count": 7, "eval_count": 3}
        elif kind == "openai":
            response = {
                "status": "completed",
                "output": [
                    {"type": "reasoning", "content": [{"text": "private reasoning"}]},
                    {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
                ],
                "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
            }
        else:
            response = {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "private reasoning", "thought": True},
                                {"text": "hello"},
                            ]
                        }
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 7,
                    "candidatesTokenCount": 3,
                    "totalTokenCount": 10,
                },
            }
        return httpx.Response(200, json=response)

    transport = httpx.MockTransport(handle)
    provider = {
        "ollama": lambda: OllamaProvider(transport=transport),
        "openai": lambda: OpenAIProvider("test-key", transport=transport),
        "gemini": lambda: GeminiProvider("test-key", transport=transport),
    }[kind]()
    reply = provider.generate(MESSAGES, model="chosen-model", timeout=1, max_output_tokens=64)
    assert reply.text == "hello"
    assert reply.usage == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    payload = json.loads(captured[0].content)
    assert "tools" not in payload
    if kind == "ollama":
        assert str(captured[0].url) == "http://127.0.0.1:11434/api/chat"
        assert payload["stream"] is False
        assert payload["options"]["num_predict"] == 64
        assert payload["messages"] == MESSAGES
    elif kind == "openai":
        assert captured[0].headers["authorization"] == "Bearer test-key"
        assert payload["store"] is False
        assert payload["input"] == MESSAGES
        assert payload["max_output_tokens"] == 64
    else:
        assert "key=" not in str(captured[0].url)
        assert captured[0].headers["x-goog-api-key"] == "test-key"
        assert payload["systemInstruction"]["parts"][0]["text"] == "Be helpful."
        assert [item["role"] for item in payload["contents"]] == ["user", "model", "user"]


@pytest.mark.parametrize(
    "status,code",
    [(401, "authentication"), (429, "rate_limit"), (500, "http_error"), (302, "http_error")],
)
def test_http_failures_redact_body_and_credentials_and_never_retry(status, code):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            text="secret-test-key private pasted content",
            headers={"location": "https://evil.test"},
        )

    provider = OpenAIProvider("secret-test-key", transport=httpx.MockTransport(handle))
    with pytest.raises(ProviderError) as failure:
        provider.generate(MESSAGES, model="model", timeout=1, max_output_tokens=64)
    assert failure.value.code == code
    assert "secret-test-key" not in str(failure.value)
    assert "private pasted content" not in str(failure.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body", [b"not json", b"[]", b'{"message":null}', b'{"message":{"content":""}}']
)
def test_malformed_and_empty_responses_are_safe_errors(body):
    provider = OllamaProvider(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    )
    with pytest.raises(ProviderError) as failure:
        provider.generate(MESSAGES, model="model", timeout=1, max_output_tokens=64)
    assert failure.value.code in {"invalid_response", "empty_response"}


def test_response_size_is_bounded():
    from jarvis.providers import MAX_RESPONSE_BYTES

    provider = OllamaProvider(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        )
    )
    with pytest.raises(ProviderError, match="size limit"):
        provider.generate(MESSAGES, model="model", timeout=1, max_output_tokens=64)


def test_cancellation_aborts_in_flight_http():
    cancel = threading.Event()
    transport_cancelled = threading.Event()

    async def handle(_):
        try:
            cancel.set()
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            transport_cancelled.set()
            raise

    provider = OllamaProvider(transport=httpx.MockTransport(handle))
    started = time.monotonic()
    with pytest.raises(ProviderCancelled):
        provider.generate(MESSAGES, model="model", timeout=2, max_output_tokens=64, cancel=cancel)
    assert time.monotonic() - started < 1
    assert transport_cancelled.is_set()


def test_total_deadline_stops_slow_provider():
    async def handle(_):
        await asyncio.sleep(10)

    provider = OllamaProvider(transport=httpx.MockTransport(handle))
    with pytest.raises(ProviderError) as failure:
        provider.generate(MESSAGES, model="model", timeout=0.05, max_output_tokens=64)
    assert failure.value.code == "timeout"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://127.0.0.1@evil.test",
        "http://127.0.0.1/private",
        "http://localhost?key=x",
        "http://localhost:bad",
    ],
)
def test_local_provider_rejects_remote_or_credential_endpoints(url):
    with pytest.raises(ProviderError):
        OllamaProvider(url)


def test_cloud_consent_checked_before_key_access(tmp_path):
    class Secrets:
        def get(self, _):
            pytest.fail("Cloud credentials must not be read without consent")

    settings = Settings(data_dir=tmp_path, provider="openai", model="chosen-model")
    with pytest.raises(ProviderError) as failure:
        create_provider(settings, Secrets())
    assert failure.value.code == "cloud_consent"
    settings.cloud_allowed = True
    with pytest.raises(ProviderError) as failure:
        create_provider(settings)
    assert failure.value.code == "missing_key"


def test_cancelled_request_never_contacts_provider():
    cancel = threading.Event()
    cancel.set()
    provider = OllamaProvider(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected network"))
    )
    with pytest.raises(ProviderCancelled):
        provider.generate(MESSAGES, model="model", timeout=1, max_output_tokens=64, cancel=cancel)

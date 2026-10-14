"""Actual NDJSON streaming bounds and opt-in service behavior; no live provider."""

import asyncio
import json
import threading
import time

import httpx
import pytest

from jarvis.config import Settings
from jarvis.providers import (
    MAX_RESPONSE_BYTES,
    MAX_STREAM_TEXT_CHARS,
    OllamaProvider,
    ProviderCancelled,
    ProviderError,
    ProviderReply,
)
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


def record(content="", *, done=False, **extra):
    return {
        "message": {"role": "assistant", "content": content},
        "done": done,
        **extra,
    }


def encode(records):
    return (
        b"\n".join(json.dumps(item, ensure_ascii=False).encode("utf-8") for item in records) + b"\n"
    )


class FragmentStream(httpx.AsyncByteStream):
    def __init__(self, parts, *, stall=False):
        self.parts = parts
        self.stall = stall
        self.closed = False
        self.cancelled = False

    async def __aiter__(self):
        try:
            for part in self.parts:
                yield part
            if self.stall:
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def aclose(self):
        self.closed = True


def stream_provider(stream, captured=None, *, status=200):
    def handle(request):
        if captured is not None:
            captured.append(request)
        return httpx.Response(
            status, stream=stream, headers={"content-type": "application/x-ndjson"}
        )

    return OllamaProvider(transport=httpx.MockTransport(handle))


def generate(provider, deltas, **kwargs):
    return provider.generate_stream(
        [{"role": "user", "content": "Explain binary numbers"}],
        model="test-model",
        timeout=1,
        max_output_tokens=64,
        on_delta=deltas.append,
        **kwargs,
    )


def test_streaming_validates_fragmented_utf8_and_omits_reasoning():
    captured, deltas = [], []
    records = [
        {
            "message": {"role": "assistant", "thinking": "private reasoning", "content": ""},
            "done": False,
        },
        record("Hello "),
        record("世界"),
        record(done=True, prompt_eval_count=7, eval_count=3, done_reason="length"),
    ]
    raw = encode(records)
    stream = FragmentStream([raw[index : index + 3] for index in range(0, len(raw), 3)])
    reply = generate(stream_provider(stream, captured), deltas)
    assert deltas == ["Hello ", "世界"]
    assert reply.text == "Hello 世界"
    assert reply.usage == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    assert reply.truncated
    assert reply.tool_calls == ()
    assert stream.closed
    payload = json.loads(captured[0].content)
    assert payload["stream"] is True
    assert "tools" not in payload
    assert payload["options"]["num_predict"] == 64
    assert len(captured) == 1


def test_legacy_thinking_tags_split_between_chunks_never_reach_receiver():
    pieces = ["<thi", "nk>private thought", "</thi", "nk>Hello ", "there"]
    deltas = []
    reply = generate(
        stream_provider(
            FragmentStream(
                [encode([record(piece)]) for piece in pieces] + [encode([record(done=True)])]
            )
        ),
        deltas,
    )
    assert deltas == ["Hello ", "there"]
    assert reply.text == "Hello there"


@pytest.mark.parametrize(
    "pieces",
    [
        ["Here is XML: <think>literal text</think>"],
        ["Here is XML: <thi", "nk>literal text</thi", "nk>"],
        ["```xml\n", "<think>literal text</think>\n```"],
        ["<think>private reasoning</think>", "```xml\n<think>literal text</think>\n```"],
    ],
    ids=["prose", "split-tag", "code", "leading-reasoning-then-code"],
)
def test_literal_think_markup_after_answer_start_is_preserved(pieces):
    deltas = []
    expected = "".join(pieces).removeprefix("<think>private reasoning</think>")
    reply = generate(
        stream_provider(
            FragmentStream(
                [encode([record(piece)]) for piece in pieces] + [encode([record(done=True)])]
            )
        ),
        deltas,
    )
    assert "".join(deltas) == expected
    assert reply.text == expected


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"not-json\n", "invalid_response"),
        (b"[]\n", "invalid_response"),
        (b"\xff\n", "invalid_response"),
        (encode([{"done": False, "message": None}]), "invalid_response"),
        (encode([{"done": 1, "message": {"content": "bad"}}]), "invalid_response"),
        (encode([{"done": False, "message": {"content": 123}}]), "invalid_response"),
        (
            encode([{"done": False, "message": {"role": "tool", "content": "bad"}}]),
            "invalid_response",
        ),
        (b'{"done":false,"done":true,"message":{"content":"bad"}}\n', "invalid_response"),
        (encode([{"error": "private pasted content secret-key"}]), "provider_error"),
        (
            encode([{"done": False, "message": {"content": "bad", "tool_calls": [{}]}}]),
            "invalid_tool_call",
        ),
        (
            encode([{"done": False, "message": {"content": "bad", "tool_calls": None}}]),
            "invalid_tool_call",
        ),
    ],
)
def test_invalid_stream_records_are_safe_and_never_emitted(raw, code):
    deltas = []
    with pytest.raises(ProviderError) as failure:
        generate(stream_provider(FragmentStream([raw])), deltas)
    assert failure.value.code == code
    assert deltas == []
    assert "private pasted content" not in str(failure.value)
    assert "secret-key" not in str(failure.value)


def test_missing_terminal_record_does_not_claim_a_completed_answer():
    deltas = []
    with pytest.raises(ProviderError) as failure:
        generate(stream_provider(FragmentStream([encode([record("Draft only")])])), deltas)
    assert deltas == ["Draft only"]
    assert failure.value.code == "incomplete_response"


def test_trailing_data_after_terminal_record_is_rejected():
    with pytest.raises(ProviderError) as failure:
        generate(
            stream_provider(
                FragmentStream([encode([record("Answer", done=True), record("Unexpected")])])
            ),
            [],
        )
    assert failure.value.code == "invalid_response"


def test_final_record_without_trailing_newline_is_valid():
    raw = encode([record("Answer"), record(done=True)]).rstrip(b"\n")
    assert generate(stream_provider(FragmentStream([raw])), []).text == "Answer"


@pytest.mark.parametrize(
    "status,code",
    [(302, "http_error"), (401, "authentication"), (429, "rate_limit"), (500, "http_error")],
)
def test_stream_http_status_never_displays_body_or_follows_redirects(status, code):
    captured, deltas = [], []
    with pytest.raises(ProviderError) as failure:
        generate(
            stream_provider(
                FragmentStream([b"secret-key private content"]), captured, status=status
            ),
            deltas,
        )
    assert failure.value.code == code
    assert deltas == []
    assert len(captured) == 1
    assert "secret-key" not in str(failure.value)


@pytest.mark.parametrize(
    "raw",
    [b"x" * (MAX_RESPONSE_BYTES + 1), encode([record("x" * (MAX_STREAM_TEXT_CHARS + 1))])],
    ids=["wire-bytes", "visible-text"],
)
def test_stream_wire_and_visible_text_limits_precede_publication(raw):
    deltas = []
    with pytest.raises(ProviderError) as failure:
        generate(stream_provider(FragmentStream([raw])), deltas)
    assert failure.value.code == "response_too_large"
    assert deltas == []


def test_stream_cancellation_closes_connection_and_stops_future_deltas():
    cancel, deltas = threading.Event(), []
    stream = FragmentStream(
        [encode([record("First")]), encode([record("Second"), record(done=True)])]
    )

    def receive(delta):
        deltas.append(delta)
        cancel.set()

    with pytest.raises(ProviderCancelled):
        stream_provider(stream).generate_stream(
            [], model="test", timeout=1, max_output_tokens=64, on_delta=receive, cancel=cancel
        )
    assert deltas == ["First"]
    assert stream.closed


def test_stream_deadline_cancels_stalled_read_and_closes_connection():
    stream = FragmentStream([encode([record("Partial")])], stall=True)
    started = time.monotonic()
    with pytest.raises(ProviderError) as failure:
        stream_provider(stream).generate_stream(
            [], model="test", timeout=0.05, max_output_tokens=64, on_delta=lambda _: None
        )
    assert failure.value.code == "timeout"
    assert time.monotonic() - started < 1
    assert stream.cancelled
    assert stream.closed


def test_pre_cancelled_stream_does_not_contact_provider():
    cancel = threading.Event()
    cancel.set()
    provider = OllamaProvider(
        transport=httpx.MockTransport(lambda _: pytest.fail("Network attempted"))
    )
    with pytest.raises(ProviderCancelled):
        generate(provider, [], cancel=cancel)


def test_stream_receiver_failure_is_redacted_and_closes_connection():
    stream = FragmentStream([encode([record("Answer"), record(done=True)])])

    def failing_receiver(_):
        raise RuntimeError("secret-key private callback state")

    with pytest.raises(ProviderError) as failure:
        stream_provider(stream).generate_stream(
            [], model="test", timeout=1, max_output_tokens=64, on_delta=failing_receiver
        )
    assert failure.value.code == "stream_receiver_error"
    assert "secret-key" not in str(failure.value)
    assert stream.closed


class StreamingStub:
    name = "ollama"

    def __init__(self):
        self.calls = []
        self.fail = False

    def generate(self, messages, **kwargs):
        self.calls.append(("final", messages))
        return ProviderReply("Final only", {})

    def generate_stream(self, messages, *, on_delta, **kwargs):
        self.calls.append(("stream", messages))
        on_delta("Hello ")
        if self.fail:
            raise ProviderError("Incomplete stream", "incomplete_response")
        on_delta("world")
        return ProviderReply("Hello world", {"total_tokens": 9}, truncated=True)


def service_for(tmp_path, provider=None, **kwargs):
    settings = Settings(data_dir=tmp_path, model="test-model", allowed_roots=[tmp_path], **kwargs)
    store = Store(tmp_path)
    engine = TaskEngine(settings, store)
    return JarvisService(settings, store, engine, provider=provider or StreamingStub())


def test_service_streaming_is_opt_in_and_preserves_final_metadata(tmp_path):
    provider = StreamingStub()
    service = service_for(tmp_path, provider)
    assert service.chat("Explain binary numbers", "chat")["text"] == "Final only"
    assert provider.calls[0][0] == "final"
    deltas = []
    reply = service.chat("Explain hexadecimal numbers", "chat", on_delta=deltas.append)
    assert provider.calls[1][0] == "stream"
    assert deltas == ["Hello ", "world"]
    assert reply["text"] == "Hello world"
    assert reply["usage"] == {"total_tokens": 9}
    assert reply["truncated"]
    assert service.store.tasks() == []


def test_streamed_code_with_literal_think_tags_survives_saved_history(tmp_path):
    code = "Example XML:\n```xml\n<think>literal text</think>\n```"
    provider = stream_provider(FragmentStream([encode([record(code), record(done=True)])]))
    service = service_for(tmp_path, provider, save_history=True)
    deltas = []
    reply = service.chat("Explain XML syntax", "chat", on_delta=deltas.append)
    assert reply["text"] == code
    assert "".join(deltas) == code
    assert service.store.history("chat")[-1] == {"role": "assistant", "content": code}


def test_cloud_stream_opt_in_keeps_final_only_behavior_and_no_local_context(tmp_path):
    provider = StreamingStub()
    service = service_for(tmp_path, provider)
    service.chat("/remember knowledge language Python", "chat")
    provider.name = "openai"
    service.settings.provider = "openai"
    service.settings.cloud_allowed = True
    deltas = []
    reply = service.chat("Explain binary numbers", "chat", on_delta=deltas.append)
    assert reply["text"] == "Final only"
    assert deltas == []
    assert provider.calls[0][0] == "final"
    assert "Python" not in str(provider.calls[0][1])


def test_provider_without_stream_support_has_no_simulated_deltas(tmp_path):
    class PlainStub:
        name = "ollama"

        def generate(self, messages, **kwargs):
            return ProviderReply("Complete response", {})

    deltas = []
    reply = service_for(tmp_path, PlainStub()).chat(
        "Explain binary numbers", on_delta=deltas.append
    )
    assert reply["text"] == "Complete response"
    assert deltas == []


def test_incomplete_stream_is_not_saved_or_used_as_followup_context(tmp_path):
    provider = StreamingStub()
    provider.fail = True
    service = service_for(tmp_path, provider, save_history=True)
    deltas = []
    with pytest.raises(ProviderError):
        service.chat("Private failed question", "chat", on_delta=deltas.append)
    assert deltas == ["Hello "]
    assert service.store.history("chat") == []
    assert "Private failed question" not in str(service.store.audits())
    service.chat("New question", "chat")
    assert "Private failed question" not in str(provider.calls[-1][1])
    assert "Hello " not in str(provider.calls[-1][1])


def test_local_memory_and_short_commands_do_not_enter_streaming_provider(tmp_path):
    provider = StreamingStub()
    service = service_for(tmp_path, provider)
    deltas = []
    service.chat("/remember knowledge language Python", on_delta=deltas.append)
    service.chat("what time is it", on_delta=deltas.append)
    assert provider.calls == []
    assert deltas == []
    assert service.store.memories()[0]["content"] == "Python"


def test_service_checks_cancel_before_publishing_a_stream_delta(tmp_path):
    cancel = threading.Event()

    class CancellingStub(StreamingStub):
        def generate_stream(self, messages, *, on_delta, **kwargs):
            cancel.set()
            on_delta("Must not appear")
            pytest.fail("Cancelled callback should abort")

    deltas = []
    with pytest.raises(ProviderCancelled):
        service_for(tmp_path, CancellingStub()).chat(
            "Explain binary numbers", cancel=cancel, on_delta=deltas.append
        )
    assert deltas == []


@pytest.mark.parametrize(
    "bad_delta,code",
    [(123, "invalid_response"), ("x" * (MAX_STREAM_TEXT_CHARS + 1), "response_too_large")],
    ids=["type", "size"],
)
def test_service_bounds_untrusted_stream_adapters_before_ui_publication(tmp_path, bad_delta, code):
    class BadStub(StreamingStub):
        def generate_stream(self, messages, *, on_delta, **kwargs):
            on_delta(bad_delta)
            pytest.fail("Invalid callback should abort")

    deltas = []
    service = service_for(tmp_path, BadStub(), save_history=True)
    with pytest.raises(ProviderError) as failure:
        service.chat("Explain binary numbers", "chat", on_delta=deltas.append)
    assert failure.value.code == code
    assert deltas == []
    assert service.store.history("chat") == []

"""Transport tests: model function calls are data, never local execution."""

import asyncio
import copy
import json
import threading

import httpx
import pytest

from jarvis.providers import (
    MAX_RESPONSE_BYTES,
    MAX_TOOL_ARGUMENT_BYTES,
    MAX_TOOL_CALLS,
    MAX_TOOL_SCHEMAS,
    GeminiProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderCancelled,
    ProviderError,
    ProviderReply,
    ProviderToolCall,
)

MESSAGES = [
    {"role": "system", "content": "Propose only."},
    {"role": "user", "content": "Open Chrome"},
]
TOOLS = [
    {
        "name": "open_app",
        "description": "Open an explicitly requested installed application.",
        "parameters": {
            "type": "object",
            "properties": {"app": {"type": "string", "enum": ["chrome", "vscode"]}},
            "required": ["app"],
            "additionalProperties": False,
        },
    }
]


def response_for(kind, calls, *, text="", truncated=False):
    if kind == "ollama":
        return {
            "message": {
                "content": text,
                "tool_calls": [
                    {
                        "type": "function",
                        "id": identifier,
                        "function": {"name": name, "arguments": arguments},
                    }
                    for name, arguments, identifier in calls
                ],
            },
            "prompt_eval_count": 5,
            "eval_count": 3,
            "done_reason": "length" if truncated else "stop",
        }
    if kind == "openai":
        outputs = [
            {
                "type": "function_call",
                "name": name,
                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                "call_id": identifier,
                "id": "response-item-id",
            }
            for name, arguments, identifier in calls
        ]
        if text:
            outputs.insert(
                0, {"type": "message", "content": [{"type": "output_text", "text": text}]}
            )
        return {
            "status": "incomplete" if truncated else "completed",
            "output": outputs,
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
    parts = [
        {"functionCall": {"name": name, "args": arguments, "id": identifier}}
        for name, arguments, identifier in calls
    ]
    if text:
        parts.insert(0, {"text": text})
    return {
        "candidates": [
            {"content": {"parts": parts}, "finishReason": "MAX_TOKENS" if truncated else "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
    }


def provider_for(kind, transport):
    if kind == "ollama":
        return OllamaProvider(transport=transport)
    if kind == "openai":
        return OpenAIProvider("secret-test-key", transport=transport)
    return GeminiProvider("secret-test-key", transport=transport)


def generate(provider, **kwargs):
    return provider.generate(
        MESSAGES, model="configured-model", timeout=1, max_output_tokens=64, **kwargs
    )


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
@pytest.mark.parametrize("text", ["", "I can propose opening Chrome."])
def test_documented_schema_payload_and_mixed_or_tool_only_response(kind, text):
    captured = []
    body = response_for(kind, [("open_app", {"app": "chrome"}, "call_1")], text=text)

    def handle(request):
        captured.append(request)
        return httpx.Response(200, json=body)

    original = copy.deepcopy(TOOLS)
    reply = generate(provider_for(kind, httpx.MockTransport(handle)), tools=TOOLS)
    assert reply.text == text
    assert reply.tool_calls == (ProviderToolCall("open_app", {"app": "chrome"}, "call_1"),)
    assert reply.usage == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
    assert TOOLS == original
    assert len(captured) == 1  # No automatic function execution or request loop.
    payload = json.loads(captured[0].content)
    if kind == "ollama":
        assert payload["tools"] == [{"type": "function", "function": TOOLS[0]}]
        assert payload["stream"] is False
    elif kind == "openai":
        assert payload["tools"] == [{"type": "function", **TOOLS[0], "strict": False}]
        assert payload["store"] is False
        assert captured[0].headers["authorization"] == "Bearer secret-test-key"
    else:
        assert payload["tools"] == [
            {
                "functionDeclarations": [
                    {
                        "name": TOOLS[0]["name"],
                        "description": TOOLS[0]["description"],
                        "parametersJsonSchema": TOOLS[0]["parameters"],
                    }
                ]
            }
        ]
        assert "key=" not in str(captured[0].url)
        assert captured[0].headers["x-goog-api-key"] == "secret-test-key"


def test_reply_positional_text_api_is_backwards_compatible():
    reply = ProviderReply("hello", {}, True)
    assert reply.truncated is True
    assert reply.tool_calls == ()


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
@pytest.mark.parametrize("tools", [None, []])
def test_no_tools_registered_for_default_or_empty_schema_list(kind, tools):
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=response_for(kind, [], text="A normal reply."))

    reply = generate(provider_for(kind, httpx.MockTransport(handle)), tools=tools)
    assert "tools" not in captured[0]
    assert reply.text == "A normal reply."
    assert reply.tool_calls == ()


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
@pytest.mark.parametrize(
    "supplied,name", [(None, "open_app"), (TOOLS, "run_shell"), (TOOLS, "x" * 65)]
)
def test_unregistered_or_unsolicited_call_rejected_including_mixed_text(kind, supplied, name):
    body = response_for(kind, [(name, {"app": "chrome"}, "call_1")], text="Already completed.")
    provider = provider_for(kind, httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=supplied)
    assert failure.value.code == "invalid_tool_call"
    assert name not in str(failure.value)


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
@pytest.mark.parametrize("arguments", [None, [], "not json", 42, True])
def test_arguments_must_be_a_json_object(kind, arguments):
    body = response_for(kind, [("open_app", arguments, "call_1")])
    provider = provider_for(kind, httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=TOOLS)
    assert failure.value.code == "invalid_tool_call"


@pytest.mark.parametrize(
    "arguments",
    [
        '{"app":"chrome","app":"vscode"}',
        '{"app":NaN}',
        '{"app":Infinity}',
        '{"app":1e999}',
        '{"app":"chrome"} private secret-test-key',
    ],
)
def test_openai_argument_json_is_strict_and_errors_redacted(arguments):
    body = response_for("openai", [("open_app", arguments, "call_1")])
    provider = provider_for("openai", httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=TOOLS)
    assert failure.value.code == "invalid_tool_call"
    assert "secret-test-key" not in str(failure.value)
    assert arguments not in str(failure.value)


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
def test_six_calls_are_preserved_but_excess_rejects_entire_batch(kind):
    calls = [("open_app", {"app": "chrome"}, f"call_{index}") for index in range(MAX_TOOL_CALLS)]
    provider = provider_for(
        kind, httpx.MockTransport(lambda _: httpx.Response(200, json=response_for(kind, calls)))
    )
    assert len(generate(provider, tools=TOOLS).tool_calls) == 6
    calls.append(("open_app", {"app": "vscode"}, "call_extra"))
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=TOOLS)
    assert failure.value.code == "invalid_tool_call"


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
@pytest.mark.parametrize("reason", ["size", "nesting", "duplicate_id", "invalid_id"])
def test_call_size_complexity_and_identifier_bounds(kind, reason):
    arguments = {"app": "chrome"}
    identifier = "call_1"
    if reason == "size":
        arguments["untrusted"] = "x" * MAX_TOOL_ARGUMENT_BYTES
    elif reason == "nesting":
        nested = arguments
        for _ in range(18):
            nested["nested"] = {}
            nested = nested["nested"]
    elif reason == "invalid_id":
        identifier = "private\nsecret-test-key"
    calls = [("open_app", arguments, identifier)]
    if reason == "duplicate_id":
        calls.append(("open_app", {"app": "vscode"}, identifier))
    provider = provider_for(
        kind, httpx.MockTransport(lambda _: httpx.Response(200, json=response_for(kind, calls)))
    )
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=TOOLS)
    assert failure.value.code == "invalid_tool_call"
    assert "secret-test-key" not in str(failure.value)


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
def test_truncation_stays_visible_for_caller_to_reject_incomplete_plans(kind):
    body = response_for(kind, [("open_app", {"app": "chrome"}, "call_1")], truncated=True)
    provider = provider_for(kind, httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    assert generate(provider, tools=TOOLS).truncated is True


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        "bad",
        [{"type": "web_search"}],
        [{**TOOLS[0], "type": "function"}],
        [{**TOOLS[0], "name": "contains spaces"}],
        [{**TOOLS[0], "name": "x" * 65}],
        [{**TOOLS[0], "description": "x" * 4097}],
        [{**TOOLS[0], "parameters": []}],
        [{**TOOLS[0], "parameters": {"type": "array"}}],
        [{**TOOLS[0], "parameters": {"type": "object", "default": float("nan")}}],
        [TOOLS[0], TOOLS[0]],
        [{**TOOLS[0], "name": f"function_{index}"} for index in range(MAX_TOOL_SCHEMAS + 1)],
    ],
)
def test_invalid_schema_definitions_never_contact_provider(invalid):
    provider = OllamaProvider(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected HTTP"))
    )
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=invalid)
    assert failure.value.code == "invalid_tools"


def test_current_tool_registry_schemas_can_be_registered_without_altering_optional_fields():
    from jarvis.tools import tool_schemas

    schemas = tool_schemas()
    captured = []

    def handle(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=response_for("openai", [], text="No action required."))

    generate(OpenAIProvider("test-key", transport=httpx.MockTransport(handle)), tools=schemas)
    assert [
        {name: item[name] for name in ("name", "description", "parameters")}
        for item in captured[0]["tools"]
    ] == schemas


@pytest.mark.parametrize("kind", ["ollama", "openai", "gemini"])
def test_tools_request_http_error_is_redacted_and_never_retried(kind):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(500, text="private command secret-test-key")

    with pytest.raises(ProviderError) as failure:
        generate(provider_for(kind, httpx.MockTransport(handle)), tools=TOOLS)
    assert failure.value.code == "http_error"
    assert "secret-test-key" not in str(failure.value)
    assert "private command" not in str(failure.value)
    assert len(requests) == 1


def test_cancellation_with_tools_aborts_in_flight_request():
    cancel, stopped = threading.Event(), threading.Event()

    async def handle(_):
        try:
            cancel.set()
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            stopped.set()
            raise

    provider = OllamaProvider(transport=httpx.MockTransport(handle))
    with pytest.raises(ProviderCancelled):
        generate(provider, tools=TOOLS, cancel=cancel)
    assert stopped.is_set()


def test_cancellation_before_tools_request_prevents_network_and_schema_processing():
    cancel = threading.Event()
    cancel.set()
    provider = OllamaProvider(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected HTTP"))
    )
    with pytest.raises(ProviderCancelled):
        generate(provider, tools="invalid schemas", cancel=cancel)


def test_tool_response_retains_existing_overall_byte_cap():
    provider = OpenAIProvider(
        "test-key",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        ),
    )
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=TOOLS)
    assert failure.value.code == "response_too_large"


def test_incomplete_openai_function_item_is_rejected():
    body = response_for("openai", [("open_app", {"app": "chrome"}, "call_1")])
    body["output"][0]["status"] = "in_progress"
    provider = OpenAIProvider(
        "test-key", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    with pytest.raises(ProviderError) as failure:
        generate(provider, tools=TOOLS)
    assert failure.value.code == "invalid_tool_call"


def test_gemini_thought_parts_are_not_promoted_to_actions_or_visible_text():
    body = response_for("gemini", [], text="A normal reply.")
    body["candidates"][0]["content"]["parts"].insert(
        0,
        {
            "thought": True,
            "text": "private reasoning",
            "functionCall": {"name": "open_app", "args": {"app": "chrome"}},
        },
    )
    provider = GeminiProvider(
        "test-key", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    reply = generate(provider, tools=TOOLS)
    assert reply.text == "A normal reply."
    assert reply.tool_calls == ()

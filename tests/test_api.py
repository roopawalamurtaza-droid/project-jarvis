import threading

import pytest
from fastapi.testclient import TestClient

from jarvis.api import create_app
from jarvis.config import Settings
from jarvis.providers import ProviderError, ProviderReply
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine

TOKEN = "test-token-at-least-16-chars"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class StubProvider:
    name = "ollama"

    def __init__(self):
        self.thread_ids = []

    def generate(self, messages, **kwargs):
        self.thread_ids.append(threading.get_ident())
        return ProviderReply("hello", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})


@pytest.fixture
def app_parts(tmp_path):
    settings = Settings(data_dir=tmp_path, model="chosen-model", allowed_roots=[tmp_path])
    store = Store(tmp_path)
    engine = TaskEngine(settings, store)
    provider = StubProvider()
    service = JarvisService(settings, store, engine, provider=provider)
    return TestClient(create_app(service, TOKEN)), service, provider


@pytest.mark.parametrize(
    "path,method",
    [
        ("/health", "get"),
        ("/chat", "post"),
        ("/memories", "get"),
        ("/tasks", "get"),
        ("/audit", "get"),
        ("/stop", "post"),
        ("/resume", "post"),
    ],
)
def test_all_surfaces_require_bearer_token(app_parts, path, method):
    client, service, provider = app_parts
    kwargs = {"json": {"message": "hello"}} if path == "/chat" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    assert (
        getattr(client, method)(
            path, headers={"Authorization": "Bearer wrong"}, **kwargs
        ).status_code
        == 401
    )
    assert provider.thread_ids == []
    assert service.store.tasks() == []


def test_empty_short_token_and_public_docs_disabled():
    for token in ("", " ", "short"):
        with pytest.raises(ValueError):
            create_app(None, token)
    app = create_app(None, TOKEN)
    assert app.openapi_url is None
    assert app.docs_url is None
    assert not any("cors" in str(middleware).lower() for middleware in app.user_middleware)


def test_authenticated_chat_reuses_service_and_does_work_off_api_thread(app_parts):
    client, service, provider = app_parts
    first = client.post("/chat", headers=AUTH, json={"message": "hello", "session_id": "chat"})
    assert first.status_code == 200
    assert first.json()["session_id"] == "chat"
    assert provider.thread_ids and provider.thread_ids[0] != threading.get_ident()
    assert service.store.audits()[0]["event"] == "chat_completed"
    assert (
        client.post("/chat", headers=AUTH, json={"message": "hello", "execute": True}).status_code
        == 422
    )


def test_memory_crud_uses_same_store_and_uuid_deletion(app_parts):
    client, service, _ = app_parts
    saved = client.post(
        "/memories",
        headers=AUTH,
        json={"category": "preferences", "key": "colour", "content": "blue"},
    )
    assert saved.status_code == 201
    memory_id = saved.json()["id"]
    assert client.get("/memories?query=blue", headers=AUTH).json()[0]["id"] == memory_id
    assert service.store.memories()[0]["content"] == "blue"
    assert client.delete(f"/memories/{memory_id}", headers=AUTH).status_code == 200
    assert service.store.memories() == []
    assert (
        client.post(
            "/memories", headers=AUTH, json={"category": "invalid", "key": "k", "content": "v"}
        ).status_code
        == 400
    )


def test_tasks_approval_replay_stop_and_audit(app_parts, tmp_path):
    client, _, _ = app_parts
    target = tmp_path / "new-folder"
    task = client.post(
        "/tasks",
        headers=AUTH,
        json={"tool": "create_directory", "arguments": {"path": str(target)}},
    )
    assert task.status_code == 201
    assert task.json()["state"] == "awaiting_approval"
    assert not target.exists()
    task_id = task.json()["id"]
    approved = client.post(f"/tasks/{task_id}/approve", headers=AUTH)
    assert approved.json()["state"] == "completed"
    assert target.exists()
    assert client.post(f"/tasks/{task_id}/approve", headers=AUTH).status_code == 409
    assert client.post("/tasks/missing/approve", headers=AUTH).status_code == 404
    assert client.get("/audit?limit=501", headers=AUTH).status_code == 422
    assert client.get("/audit", headers=AUTH).status_code == 200
    assert client.post("/stop", headers=AUTH).json() == {"stopped": True}
    assert client.post("/chat", headers=AUTH, json={"message": "stopped"}).status_code == 409
    assert (
        client.post(
            "/tasks",
            headers=AUTH,
            json={"tool": "list_directory", "arguments": {"path": str(tmp_path)}},
        ).status_code
        == 409
    )
    assert client.post("/resume", headers=AUTH).json() == {"stopped": False}


def test_provider_failures_are_safe_and_request_cap_applies(app_parts):
    client, service, provider = app_parts
    service.settings.max_requests_per_session = 1

    def fail(*args, **kwargs):
        raise ProviderError("Could not reach the selected provider.", "connection_error")

    provider.generate = fail
    assert (
        client.post(
            "/chat", headers=AUTH, json={"message": "hello", "session_id": "chat"}
        ).status_code
        == 502
    )
    assert (
        client.post(
            "/chat", headers=AUTH, json={"message": "hello", "session_id": "chat"}
        ).status_code
        == 429
    )


def test_arbitrary_tool_and_outside_workspace_denied(app_parts, tmp_path):
    client, _, _ = app_parts
    shell = client.post(
        "/tasks", headers=AUTH, json={"tool": "shell", "arguments": {"command": "whoami"}}
    )
    assert shell.status_code == 400
    outside = client.post(
        "/tasks",
        headers=AUTH,
        json={"tool": "read_file", "arguments": {"path": str(tmp_path.parent / "private.txt")}},
    )
    assert outside.status_code == 400


def test_api_body_size_and_authentication_precede_json_parsing(app_parts):
    from jarvis.api import MAX_API_BODY_BYTES

    client, _, provider = app_parts
    body = "x" * (MAX_API_BODY_BYTES + 1)
    assert client.post("/chat", content=body).status_code == 401
    assert client.post("/chat", headers=AUTH, content=body).status_code == 413
    assert client.post("/chat", headers=AUTH, json={"message": "x" * 12001}).status_code == 422
    assert provider.thread_ids == []

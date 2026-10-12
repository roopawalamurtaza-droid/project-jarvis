"""Optional authenticated loopback HTTP facade over the same desktop service."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .providers import ProviderError
from .service import MAX_MESSAGE_CHARS, ServiceError

MAX_API_BODY_BYTES = 256 * 1024


class _BoundedRequests:
    """Authenticate before reading a request body, then enforce a byte limit."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        supplied = [value for name, value in headers if name.lower() == b"authorization"]
        if len(supplied) != 1 or not secrets.compare_digest(supplied[0], self.expected):
            await JSONResponse(
                status_code=401, content={"detail": "Valid bearer authentication is required."}
            )(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_API_BODY_BYTES:
                await JSONResponse(
                    status_code=413, content={"detail": "The request body exceeds the size limit."}
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatInput(_Input):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)


class MemoryInput(_Input):
    category: str = Field(min_length=1, max_length=80)
    key: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class TaskInput(_Input):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


def create_app(service, token: str) -> FastAPI:
    if not isinstance(token, str) or len(token.strip()) < 16:
        raise ValueError("The local API requires a token of at least 16 characters.")

    # No public docs, wildcard CORS, cookie authentication, or query-string tokens.
    app = FastAPI(title="JARVIS local API", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(_BoundedRequests, token=token)

    @app.exception_handler(ServiceError)
    async def service_error(_request, exc):
        status = 429 if exc.code in ("request_limit", "session_limit") else 400
        return JSONResponse(status_code=status, content={"detail": str(exc), "code": exc.code})

    @app.exception_handler(ProviderError)
    async def provider_error(_request, exc):
        statuses = {"cancelled": 409, "cloud_consent": 403, "missing_key": 400, "timeout": 504}
        return JSONResponse(
            status_code=statuses.get(exc.code, 502), content={"detail": str(exc), "code": exc.code}
        )

    @app.get("/health")
    async def health():
        return {
            "status": "stopped" if service.stopped else "ok",
            "provider": service.settings.provider,
        }

    @app.post("/chat")
    async def chat(request: ChatInput):
        return await run_in_threadpool(service.chat, request.message, request.session_id)

    @app.get("/sessions")
    async def sessions():
        return await run_in_threadpool(service.store.sessions)

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str):
        await run_in_threadpool(service.delete_session, session_id)
        return {"deleted": True}

    @app.get("/memories")
    async def memories(query: str = Query(default="", max_length=500)):
        return await run_in_threadpool(service.store.memories, query)

    @app.post("/memories", status_code=201)
    async def save_memory(request: MemoryInput):
        return await run_in_threadpool(
            service.save_memory, request.category, request.key, request.content
        )

    @app.delete("/memories/{memory_id}")
    async def delete_memory(memory_id: str):
        await run_in_threadpool(service.store.delete_memory, memory_id)
        return {"deleted": True}

    @app.get("/tasks")
    async def tasks():
        return await run_in_threadpool(service.store.tasks)

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        task = await run_in_threadpool(service.store.get_task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task

    @app.post("/tasks", status_code=201)
    async def submit_task(request: TaskInput):
        if service.stopped:
            raise HTTPException(
                status_code=409, detail="JARVIS is stopped. Resume before submitting a task."
            )
        if len(str(request.arguments)) > MAX_MESSAGE_CHARS:
            raise HTTPException(status_code=413, detail="The task arguments exceed the size limit.")
        try:
            return await run_in_threadpool(service.engine.submit, request.tool, request.arguments)
        except (ValueError, PermissionError):
            raise HTTPException(
                status_code=400, detail="The local tool or its arguments are invalid."
            ) from None

    async def task_action(action, task_id):
        if await run_in_threadpool(service.store.get_task, task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        try:
            return await run_in_threadpool(action, task_id)
        except (ValueError, PermissionError):
            raise HTTPException(
                status_code=409, detail="This task cannot perform the requested transition."
            ) from None

    @app.post("/tasks/{task_id}/approve")
    async def approve_task(task_id: str):
        if service.stopped:
            raise HTTPException(
                status_code=409, detail="JARVIS is stopped. Resume before approving a task."
            )
        return await task_action(service.engine.approve, task_id)

    @app.post("/tasks/{task_id}/reject")
    async def reject_task(task_id: str):
        return await task_action(service.engine.reject, task_id)

    @app.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str):
        return await task_action(service.engine.cancel, task_id)

    @app.get("/audit")
    async def audit(limit: int = Query(default=100, ge=1, le=500)):
        return await run_in_threadpool(service.store.audits, limit)

    @app.post("/stop")
    async def stop():
        await run_in_threadpool(service.emergency_stop)
        return {"stopped": True}

    @app.post("/resume")
    async def resume():
        await run_in_threadpool(service.reset_stop)
        return {"stopped": False}

    return app

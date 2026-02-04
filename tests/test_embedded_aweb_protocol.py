from __future__ import annotations

import uuid

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from beadhub.api import create_app

TEST_REDIS_URL = "redis://localhost:6379/15"


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


@pytest.mark.asyncio
async def test_embedded_aweb_mail_chat_reservations_roundtrip(db_infra, init_workspace):
    redis = await Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        pytest.skip("Redis is not available")
    await redis.flushdb()

    try:
        app = create_app(db_infra=db_infra, redis=redis, serve_frontend=False)
        async with LifespanManager(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                project_slug = f"embedded-aweb-{uuid.uuid4().hex[:8]}"

                ws1 = await init_workspace(
                    client,
                    project_slug=project_slug,
                    repo_origin="git@github.com:test/embedded-aweb-1.git",
                    alias="agent-1",
                )
                ws2 = await init_workspace(
                    client,
                    project_slug=project_slug,
                    repo_origin="git@github.com:test/embedded-aweb-2.git",
                    alias="agent-2",
                )

                headers_1 = _auth_headers(ws1["api_key"])
                headers_2 = _auth_headers(ws2["api_key"])

                # aweb mail
                send = await client.post(
                    "/v1/messages",
                    headers=headers_1,
                    json={
                        "to_agent_id": ws2["workspace_id"],
                        "subject": "hello",
                        "body": "world",
                        "priority": "normal",
                    },
                )
                assert send.status_code == 200, send.text
                message_id = send.json()["message_id"]

                inbox = await client.get(
                    "/v1/messages/inbox",
                    headers=headers_2,
                    params={"unread_only": True, "limit": 50},
                )
                assert inbox.status_code == 200, inbox.text
                assert any(
                    m.get("message_id") == message_id for m in (inbox.json().get("messages") or [])
                )

                # aweb chat
                chat = await client.post(
                    "/v1/chat/sessions",
                    headers=headers_1,
                    json={
                        "to_aliases": ["agent-2"],
                        "message": "ping",
                        "leaving": False,
                    },
                )
                assert chat.status_code == 200, chat.text
                session_id = chat.json()["session_id"]

                pending = await client.get(
                    "/v1/chat/pending",
                    headers=headers_2,
                )
                assert pending.status_code == 200, pending.text
                assert any(
                    p.get("session_id") == session_id for p in (pending.json().get("pending") or [])
                )

                # aweb reservations
                resource_key = f"embedded-aweb:{uuid.uuid4().hex}"
                lock = await client.post(
                    "/v1/reservations",
                    headers=headers_1,
                    json={
                        "resource_key": resource_key,
                        "ttl_seconds": 60,
                        "metadata": {},
                    },
                )
                assert lock.status_code in (200, 201), lock.text

                locks = await client.get(
                    "/v1/reservations",
                    headers=headers_1,
                    params={"prefix": "embedded-aweb:"},
                )
                assert locks.status_code == 200, locks.text
                keys = [r.get("resource_key") for r in (locks.json().get("reservations") or [])]
                assert resource_key in keys
    finally:
        await redis.flushdb()
        await redis.aclose()

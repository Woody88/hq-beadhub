from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request

from beadhub.aweb_introspection import get_project_from_auth
from beadhub.db import DatabaseInfra
from beadhub.internal_auth import _internal_auth_header_value


@pytest.mark.asyncio
async def test_beadhub_get_project_from_auth_uses_local_verify_when_no_proxy_headers():
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", b"Bearer some-token")],
        }
    )

    db = AsyncMock(spec=DatabaseInfra)

    with patch(
        "beadhub.aweb_introspection.verify_bearer_token_details",
        new=AsyncMock(return_value={"project_id": "proj-123", "api_key_id": "k-1", "agent_id": None, "user_id": None}),
    ) as mocked:
        got = await get_project_from_auth(request, db)

    assert got == "proj-123"
    mocked.assert_awaited_once_with(db, "some-token", manager_name="aweb")


@pytest.mark.asyncio
async def test_beadhub_get_project_from_auth_accepts_valid_proxy_headers(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("BEADHUB_INTERNAL_AUTH_SECRET", secret)

    project_id = str(uuid.uuid4())
    principal_id = str(uuid.uuid4())
    actor_id = str(uuid.uuid4())
    internal_auth = _internal_auth_header_value(
        secret=secret,
        project_id=str(uuid.UUID(project_id)),
        principal_type="u",
        principal_id=principal_id,
        actor_id=actor_id,
    )

    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-bh-auth", internal_auth.encode("utf-8")),
                (b"x-project-id", project_id.encode("utf-8")),
                (b"x-user-id", principal_id.encode("utf-8")),
                (b"x-aweb-actor-id", actor_id.encode("utf-8")),
            ],
        }
    )
    db = AsyncMock(spec=DatabaseInfra)

    with patch(
        "beadhub.aweb_introspection.verify_bearer_token_details",
        new=AsyncMock(side_effect=AssertionError("verify_bearer_token_details should not be called")),
    ):
        got = await get_project_from_auth(request, db)
    assert got == str(uuid.UUID(project_id))


@pytest.mark.asyncio
async def test_beadhub_get_project_from_auth_ignores_proxy_headers_when_no_secret(monkeypatch):
    monkeypatch.delenv("BEADHUB_INTERNAL_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)

    project_id = str(uuid.uuid4())
    internal_auth = "v1:ignored:u:user-123:deadbeef"

    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-bh-auth", internal_auth.encode("utf-8")),
                (b"x-project-id", project_id.encode("utf-8")),
                (b"x-user-id", b"user-123"),
                (b"authorization", b"Bearer some-token"),
            ],
        }
    )
    db = AsyncMock(spec=DatabaseInfra)

    with patch(
        "beadhub.aweb_introspection.verify_bearer_token_details",
        new=AsyncMock(return_value={"project_id": "proj-123", "api_key_id": "k-1", "agent_id": None, "user_id": None}),
    ) as mocked:
        got = await get_project_from_auth(request, db)
    assert got == "proj-123"
    mocked.assert_awaited_once_with(db, "some-token", manager_name="aweb")


@pytest.mark.asyncio
async def test_beadhub_get_project_from_auth_rejects_invalid_proxy_signature(monkeypatch):
    secret = "test-secret"
    monkeypatch.setenv("BEADHUB_INTERNAL_AUTH_SECRET", secret)

    project_id = str(uuid.uuid4())
    principal_id = str(uuid.uuid4())
    actor_id = str(uuid.uuid4())
    internal_auth = "v2:" + project_id + ":u:" + principal_id + ":" + actor_id + ":deadbeef"

    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-bh-auth", internal_auth.encode("utf-8")),
                (b"x-project-id", project_id.encode("utf-8")),
                (b"x-user-id", principal_id.encode("utf-8")),
                (b"x-aweb-actor-id", actor_id.encode("utf-8")),
            ],
        }
    )
    db = AsyncMock(spec=DatabaseInfra)

    with patch(
        "beadhub.aweb_introspection.verify_bearer_token_details",
        new=AsyncMock(side_effect=AssertionError("verify_bearer_token_details should not be called")),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await get_project_from_auth(request, db)
    assert exc_info.value.status_code == 401

"""Tests for tenant isolation in escalation endpoints.

These tests verify that a project-scoped Bearer API key cannot be used to
access or mutate escalations belonging to a different project.
"""

import uuid

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from beadhub.api import create_app

TEST_REDIS_URL = "redis://localhost:6379/15"


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


async def init_workspace(
    client: AsyncClient,
    *,
    project_slug: str,
    repo_origin: str,
    alias: str,
    human_name: str,
) -> dict:
    aweb_resp = await client.post(
        "/v1/init",
        json={
            "project_slug": project_slug,
            "project_name": project_slug,
            "alias": alias,
            "human_name": human_name,
            "agent_type": "agent",
        },
    )
    assert aweb_resp.status_code == 200, aweb_resp.text
    api_key = aweb_resp.json()["api_key"]
    assert api_key.startswith("aw_sk_")

    resp = await client.post(
        "/v1/workspaces/register",
        headers=auth_headers(api_key),
        json={"repo_origin": repo_origin, "role": "agent"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    data["api_key"] = api_key
    return data


async def create_escalation(
    client: AsyncClient,
    *,
    api_key: str,
    workspace_id: str,
    alias: str,
    subject: str,
) -> str:
    resp = await client.post(
        "/v1/escalations",
        json={
            "workspace_id": workspace_id,
            "alias": alias,
            "subject": subject,
            "situation": "Test escalation situation",
            "options": ["Option 1", "Option 2"],
        },
        headers=auth_headers(api_key),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["escalation_id"]


@pytest.mark.asyncio
async def test_create_escalation_cross_tenant_returns_403(db_infra):
    """Project B cannot create an escalation for Project A's workspace."""
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
                a = await init_workspace(
                    client,
                    project_slug=f"create-iso-a-{uuid.uuid4().hex[:6]}",
                    repo_origin=f"git@github.com:test/create-iso-a-{uuid.uuid4().hex[:6]}.git",
                    alias="agent-a",
                    human_name="Owner A",
                )
                b = await init_workspace(
                    client,
                    project_slug=f"create-iso-b-{uuid.uuid4().hex[:6]}",
                    repo_origin=f"git@github.com:test/create-iso-b-{uuid.uuid4().hex[:6]}.git",
                    alias="agent-b",
                    human_name="Owner B",
                )

                # Project A can create for their own workspace.
                esc_id = await create_escalation(
                    client,
                    api_key=a["api_key"],
                    workspace_id=a["workspace_id"],
                    alias="agent-a",
                    subject="A's escalation",
                )
                assert esc_id

                # Project B cannot create for Project A's workspace.
                resp_b = await client.post(
                    "/v1/escalations",
                    json={
                        "workspace_id": a["workspace_id"],
                        "alias": "agent-a",
                        "subject": "Cross-tenant attack",
                        "situation": "Malicious escalation",
                        "options": ["Hack", "Attack"],
                    },
                    headers=auth_headers(b["api_key"]),
                )
                assert resp_b.status_code == 403
    finally:
        await redis.flushdb()
        await redis.aclose()


@pytest.mark.asyncio
async def test_create_escalation_rejects_workspace_id_spoofing_within_project(db_infra):
    """An agent API key must not be able to create an escalation for another workspace in the same project."""
    redis = await Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        pytest.skip("Redis is not available")
    await redis.flushdb()

    try:
        app = create_app(db_infra=db_infra, redis=redis, serve_frontend=False)
        async with LifespanManager(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                project_slug = f"escalation-spoof-{uuid.uuid4().hex[:6]}"
                repo_origin = f"git@github.com:test/{project_slug}.git"
                a = await init_workspace(
                    client,
                    project_slug=project_slug,
                    repo_origin=repo_origin,
                    alias="agent-a",
                    human_name="Owner A",
                )
                b = await init_workspace(
                    client,
                    project_slug=project_slug,
                    repo_origin=repo_origin,
                    alias="agent-b",
                    human_name="Owner B",
                )

                resp = await client.post(
                    "/v1/escalations",
                    json={
                        "workspace_id": b["workspace_id"],
                        "alias": "agent-b",
                        "subject": "spoof attempt",
                        "situation": "should be rejected",
                        "options": ["x"],
                    },
                    headers=auth_headers(a["api_key"]),
                )
                assert resp.status_code == 403, resp.text
    finally:
        await redis.flushdb()
        await redis.aclose()


@pytest.mark.asyncio
async def test_get_escalation_cross_tenant_returns_404(db_infra):
    """Project B cannot access Project A's escalation (returns 404)."""
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
                a = await init_workspace(
                    client,
                    project_slug=f"escalation-iso-a-{uuid.uuid4().hex[:6]}",
                    repo_origin=f"git@github.com:test/esc-iso-a-{uuid.uuid4().hex[:6]}.git",
                    alias="agent-a",
                    human_name="Owner A",
                )
                b = await init_workspace(
                    client,
                    project_slug=f"escalation-iso-b-{uuid.uuid4().hex[:6]}",
                    repo_origin=f"git@github.com:test/esc-iso-b-{uuid.uuid4().hex[:6]}.git",
                    alias="agent-b",
                    human_name="Owner B",
                )

                escalation_id = await create_escalation(
                    client,
                    api_key=a["api_key"],
                    workspace_id=a["workspace_id"],
                    alias="agent-a",
                    subject="A's secret escalation",
                )

                resp_a = await client.get(
                    f"/v1/escalations/{escalation_id}",
                    headers=auth_headers(a["api_key"]),
                )
                assert resp_a.status_code == 200
                assert resp_a.json()["subject"] == "A's secret escalation"

                resp_b = await client.get(
                    f"/v1/escalations/{escalation_id}",
                    headers=auth_headers(b["api_key"]),
                )
                assert resp_b.status_code == 404
    finally:
        await redis.flushdb()
        await redis.aclose()


@pytest.mark.asyncio
async def test_respond_escalation_cross_tenant_returns_404(db_infra):
    """Project B cannot respond to Project A's escalation (returns 404)."""
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
                a = await init_workspace(
                    client,
                    project_slug=f"respond-iso-a-{uuid.uuid4().hex[:6]}",
                    repo_origin=f"git@github.com:test/respond-iso-a-{uuid.uuid4().hex[:6]}.git",
                    alias="agent-a",
                    human_name="Owner A",
                )
                b = await init_workspace(
                    client,
                    project_slug=f"respond-iso-b-{uuid.uuid4().hex[:6]}",
                    repo_origin=f"git@github.com:test/respond-iso-b-{uuid.uuid4().hex[:6]}.git",
                    alias="agent-b",
                    human_name="Owner B",
                )

                escalation_id = await create_escalation(
                    client,
                    api_key=a["api_key"],
                    workspace_id=a["workspace_id"],
                    alias="agent-a",
                    subject="A's escalation",
                )

                resp_b = await client.post(
                    f"/v1/escalations/{escalation_id}/respond",
                    json={"response": "Option 1", "note": "nope"},
                    headers=auth_headers(b["api_key"]),
                )
                assert resp_b.status_code == 404
    finally:
        await redis.flushdb()
        await redis.aclose()

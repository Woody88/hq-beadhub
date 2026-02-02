"""Tests for escalation workspace_id storage and event publishing."""

import asyncio
import json
import uuid

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from beadhub.api import create_app
from beadhub.events import EscalationRespondedEvent

# =============================================================================
# Helpers
# =============================================================================

_LAST_REPO_ORIGIN: str | None = None
_LAST_PROJECT_SLUG: str | None = None


async def _create_project_and_repo(client) -> tuple[str, str]:
    project_slug = f"test-{uuid.uuid4().hex[:8]}"
    repo_origin = f"git@github.com:test/escalations-{project_slug}.git"
    global _LAST_REPO_ORIGIN
    _LAST_REPO_ORIGIN = repo_origin
    global _LAST_PROJECT_SLUG
    _LAST_PROJECT_SLUG = project_slug

    aweb_resp = await client.post(
        "/v1/init",
        json={
            "project_slug": project_slug,
            "project_name": project_slug,
            "alias": f"init-{uuid.uuid4().hex[:8]}",
            "human_name": "Init User",
            "agent_type": "agent",
        },
    )
    assert aweb_resp.status_code == 200, aweb_resp.text
    api_key = aweb_resp.json()["api_key"]
    client.headers["Authorization"] = f"Bearer {api_key}"

    reg_resp = await client.post(
        "/v1/workspaces/register",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"repo_origin": repo_origin, "role": "agent"},
    )
    assert reg_resp.status_code == 200, reg_resp.text
    data = reg_resp.json()
    return data["project_id"], data["repo_id"]


async def _register_workspace(client, project_id: str, repo_id: str, alias: str) -> str:
    if _LAST_REPO_ORIGIN is None:
        raise RuntimeError("_create_project_and_repo must be called before _register_workspace")
    if _LAST_PROJECT_SLUG is None:
        raise RuntimeError("_create_project_and_repo must be called before _register_workspace")

    aweb_resp = await client.post(
        "/v1/init",
        json={
            "project_slug": _LAST_PROJECT_SLUG,
            "project_name": _LAST_PROJECT_SLUG,
            "alias": alias,
            "human_name": "Test User",
            "agent_type": "agent",
        },
    )
    assert aweb_resp.status_code == 200, aweb_resp.text
    api_key = aweb_resp.json()["api_key"]

    resp = await client.post(
        "/v1/workspaces/register",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"repo_origin": _LAST_REPO_ORIGIN, "role": "agent"},
    )
    assert resp.status_code == 200, resp.text
    # Subsequent requests should act as this workspace's agent identity.
    client.headers["Authorization"] = f"Bearer {api_key}"
    return resp.json()["workspace_id"]


# =============================================================================
# Test workspace_id is stored in escalation
# =============================================================================


@pytest.mark.asyncio
async def test_escalation_stores_workspace_id(db_infra, redis_client_async):
    """Creating an escalation stores the workspace_id so it can be retrieved."""
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            project_id, repo_id = await _create_project_and_repo(client)
            workspace_id = await _register_workspace(client, project_id, repo_id, "test-agent")
            # Create escalation
            esc_payload = {
                "workspace_id": workspace_id,
                "alias": "test-agent",
                "subject": "Test escalation",
                "situation": "Testing workspace_id storage",
                "options": ["Option A", "Option B"],
                "expires_in_hours": 1,
            }
            resp = await client.post("/v1/escalations", json=esc_payload)
            assert resp.status_code == 200
            escalation_id = resp.json()["escalation_id"]

            # Get escalation detail - workspace_id should be present
            detail_resp = await client.get(f"/v1/escalations/{escalation_id}")
            assert detail_resp.status_code == 200
            detail = detail_resp.json()

            # This is the failing assertion - workspace_id is not currently stored
            assert detail.get("workspace_id") == workspace_id


# =============================================================================
# Test EscalationRespondedEvent is published
# =============================================================================


@pytest.mark.asyncio
async def test_escalation_responded_event_serialization():
    """EscalationRespondedEvent serializes correctly."""
    event = EscalationRespondedEvent(
        workspace_id="ws-123",
        escalation_id="esc-456",
        response="Option A",
    )

    data = event.to_dict()
    assert data["type"] == "escalation.responded"
    assert data["workspace_id"] == "ws-123"
    assert data["escalation_id"] == "esc-456"
    assert data["response"] == "Option A"


@pytest.mark.asyncio
async def test_respond_escalation_publishes_event(db_infra, redis_client_async):
    """Responding to an escalation publishes EscalationRespondedEvent."""
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            project_id, repo_id = await _create_project_and_repo(client)
            workspace_id = await _register_workspace(client, project_id, repo_id, "test-agent")
            # Create escalation
            esc_payload = {
                "workspace_id": workspace_id,
                "alias": "test-agent",
                "subject": "Test escalation",
                "situation": "Testing event publishing",
                "options": ["Option A", "Option B"],
                "expires_in_hours": 1,
            }
            resp = await client.post("/v1/escalations", json=esc_payload)
            assert resp.status_code == 200
            escalation_id = resp.json()["escalation_id"]

            # Subscribe to workspace's event channel using async Redis
            pubsub = redis_client_async.pubsub()
            await pubsub.subscribe(f"events:{workspace_id}")

            # Consume subscribe confirmation
            msg = await pubsub.get_message(timeout=1.0)
            assert msg is not None
            assert msg["type"] == "subscribe"

            # Respond to escalation
            respond_payload = {
                "response": "Option A",
                "note": "Test response",
            }
            respond_resp = await client.post(
                f"/v1/escalations/{escalation_id}/respond", json=respond_payload
            )
            assert respond_resp.status_code == 200

            # Check for EscalationRespondedEvent
            # Give Redis a moment to deliver the message
            await asyncio.sleep(0.1)
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)

            # This will fail - event is not currently published
            assert msg is not None, "Expected EscalationRespondedEvent to be published"
            assert msg["type"] == "message"
            data = json.loads(msg["data"])
            assert data["type"] == "escalation.responded"
            assert data["escalation_id"] == escalation_id
            assert data["response"] == "Option A"

            await pubsub.unsubscribe()
            await pubsub.aclose()

import re

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from beadhub.api import create_app


@pytest.mark.asyncio
async def test_beadhub_init_with_repo_origin_creates_workspace(db_infra, redis_client_async):
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-combined",
                    "project_name": "test-init-combined",
                    "repo_origin": "git@github.com:test/init-combined.git",
                    "alias": "init-agent",
                    "human_name": "Init User",
                    "role": "agent",
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "ok"
            assert data["api_key"].startswith("aw_sk_")
            assert data["created_at"]
            assert data["project_id"]
            assert data["project_slug"] == "test-init-combined"
            assert data["agent_id"]
            assert data["repo_id"]
            assert data["workspace_id"]
            assert data["canonical_origin"] == "github.com/test/init-combined"
            assert data["alias"] == "init-agent"
            assert data["created"] is True
            assert data["workspace_created"] is True

            # Second call should be idempotent for workspace_id.
            resp2 = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-combined",
                    "project_name": "test-init-combined",
                    "repo_origin": "git@github.com:test/init-combined.git",
                    "alias": "init-agent",
                    "human_name": "Init User",
                    "role": "agent",
                },
            )
            assert resp2.status_code == 200, resp2.text
            data2 = resp2.json()
            assert data2["workspace_id"] == data["workspace_id"]
            assert data2["created"] is False
            assert data2["workspace_created"] is False


@pytest.mark.asyncio
async def test_beadhub_init_suggests_alias_when_missing(db_infra, redis_client_async):
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-suggest",
                    "project_name": "test-init-suggest",
                    "repo_origin": "git@github.com:test/init-suggest.git",
                    "human_name": "Init User",
                    "role": "reviewer",
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["api_key"].startswith("aw_sk_")
            assert re.match(r"^[a-z]+(-\\d\\d)?-reviewer$", data["alias"]), data["alias"]


@pytest.mark.asyncio
async def test_beadhub_init_requires_project_slug_for_new_repo(db_infra, redis_client_async):
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "repo_origin": "git@github.com:test/init-missing-project.git",
                    "alias": "init-agent",
                },
            )
            assert resp.status_code == 422
            assert "project_not_found" in resp.text or "project_slug is required" in resp.text


@pytest.mark.asyncio
async def test_beadhub_init_rejects_invalid_hostname(db_infra, redis_client_async):
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-hostname-invalid",
                    "project_name": "test-init-hostname-invalid",
                    "repo_origin": "git@github.com:test/init-hostname-invalid.git",
                    "alias": "init-agent",
                    "hostname": "bad\x00host",
                },
            )
            assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_beadhub_init_rejects_invalid_workspace_path(db_infra, redis_client_async):
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-path-invalid",
                    "project_name": "test-init-path-invalid",
                    "repo_origin": "git@github.com:test/init-path-invalid.git",
                    "alias": "init-agent",
                    "workspace_path": "/tmp/bad\x00path",
                },
            )
            assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_beadhub_init_returns_409_when_alias_already_bound_to_different_repo(
    db_infra, redis_client_async
):
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp1 = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-repo-mismatch",
                    "project_name": "test-init-repo-mismatch",
                    "repo_origin": "git@github.com:test/repo-a.git",
                    "alias": "mismatch-agent",
                    "human_name": "Init User",
                    "role": "agent",
                },
            )
            assert resp1.status_code == 200, resp1.text

            resp2 = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-repo-mismatch",
                    "project_name": "test-init-repo-mismatch",
                    "repo_origin": "git@github.com:test/repo-b.git",
                    "alias": "mismatch-agent",
                    "human_name": "Init User",
                    "role": "agent",
                },
            )
            assert resp2.status_code == 409, resp2.text
            assert "workspace_repo_mismatch" in resp2.text
            assert "github.com/test/repo-a" in resp2.text
            assert "github.com/test/repo-b" in resp2.text


@pytest.mark.asyncio
async def test_beadhub_init_returns_identity_fields(db_infra, redis_client_async):
    """Init response includes did, custody, and lifetime from aweb identity."""
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-identity",
                    "repo_origin": "git@github.com:test/init-identity.git",
                    "alias": "id-agent",
                    "role": "agent",
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["did"] is not None
            assert data["did"].startswith("did:key:z")
            assert data["custody"] == "custodial"
            assert data["lifetime"] == "ephemeral"


@pytest.mark.asyncio
async def test_beadhub_init_persistent_override(db_infra, redis_client_async):
    """Caller can override lifetime to persistent."""
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-persistent",
                    "repo_origin": "git@github.com:test/init-persistent.git",
                    "alias": "persist-agent",
                    "role": "agent",
                    "lifetime": "persistent",
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["lifetime"] == "persistent"
            assert data["custody"] == "custodial"
            assert data["did"].startswith("did:key:z")


@pytest.mark.asyncio
async def test_beadhub_init_without_repo_returns_identity_fields(db_infra, redis_client_async):
    """Init without repo_origin (aweb-only) also returns identity fields."""
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-init-no-repo-id",
                    "alias": "norep-agent",
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["did"] is not None
            assert data["custody"] == "custodial"
            assert data["lifetime"] == "ephemeral"

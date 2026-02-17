"""Tests for project isolation in /v1/init.

Verifies that projects with the same slug but different project_ids
(multi-tenant cloud scenario) get separate aweb project records and
independent alias pools.
"""

import uuid

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from beadhub.api import create_app


async def _pre_create_project(db_infra, *, slug: str, tenant_id: str) -> str:
    """Insert a project into server.projects (simulating beadhub-cloud).

    Returns the project_id.
    """
    project_id = uuid.uuid4()
    server_db = db_infra.get_manager("server")
    await server_db.execute(
        """
        INSERT INTO {{tables.projects}} (id, tenant_id, slug, name)
        VALUES ($1, $2, $3, $4)
        """,
        project_id,
        uuid.UUID(tenant_id),
        slug,
        slug,
    )
    return str(project_id)


@pytest.mark.asyncio
async def test_init_with_project_id_isolates_alias_pools(db_infra, redis_client_async):
    """Two cloud projects with the same slug but different project_ids get independent aliases."""
    slug = f"shared-{uuid.uuid4().hex[:8]}"
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    # Simulate beadhub-cloud creating two projects with the same slug for different tenants
    pid_a = await _pre_create_project(db_infra, slug=slug, tenant_id=tenant_a)
    pid_b = await _pre_create_project(db_infra, slug=slug, tenant_id=tenant_b)

    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Init first agent in project A
            resp_a = await client.post(
                "/v1/init",
                json={
                    "project_slug": slug,
                    "project_id": pid_a,
                    "project_name": slug,
                    "human_name": "Agent A1",
                    "agent_type": "agent",
                    "repo_origin": f"git@github.com:test/{slug}-a.git",
                    "role": "agent",
                },
            )
            assert resp_a.status_code == 200, resp_a.text
            alias_a1 = resp_a.json()["alias"]
            project_id_a = resp_a.json()["project_id"]

            # Init first agent in project B (same slug, different project_id)
            resp_b = await client.post(
                "/v1/init",
                json={
                    "project_slug": slug,
                    "project_id": pid_b,
                    "project_name": slug,
                    "human_name": "Agent B1",
                    "agent_type": "agent",
                    "repo_origin": f"git@github.com:test/{slug}-b.git",
                    "role": "agent",
                },
            )
            assert resp_b.status_code == 200, resp_b.text
            alias_b1 = resp_b.json()["alias"]
            project_id_b = resp_b.json()["project_id"]

            # Both should get the first name prefix (e.g., "alice-agent")
            # because their alias pools are independent
            assert alias_a1 == alias_b1, (
                f"Expected same alias prefix for first agent in each project, "
                f"got {alias_a1!r} vs {alias_b1!r}"
            )

            # Project IDs should match what we pre-created
            assert project_id_a == pid_a
            assert project_id_b == pid_b

            # They should be different aweb projects
            assert pid_a != pid_b


@pytest.mark.asyncio
async def test_init_without_project_id_still_works(db_infra, redis_client_async):
    """OSS mode: /v1/init without project_id works as before."""
    slug = f"oss-{uuid.uuid4().hex[:8]}"

    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": slug,
                    "project_name": slug,
                    "human_name": "OSS Agent",
                    "agent_type": "agent",
                    "repo_origin": f"git@github.com:test/{slug}.git",
                    "role": "agent",
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["alias"]  # Got an alias
            assert data["project_id"]  # Got a project ID
            assert data["workspace_id"]  # Got a workspace


@pytest.mark.asyncio
async def test_init_with_project_id_uses_existing_server_project(db_infra, redis_client_async):
    """When project_id is provided, the returned project_id matches it."""
    slug = f"cloud-{uuid.uuid4().hex[:8]}"
    tenant_id = str(uuid.uuid4())
    pre_created_pid = await _pre_create_project(db_infra, slug=slug, tenant_id=tenant_id)

    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": slug,
                    "project_id": pre_created_pid,
                    "project_name": slug,
                    "human_name": "Cloud Agent",
                    "agent_type": "agent",
                    "repo_origin": f"git@github.com:test/{slug}.git",
                    "role": "agent",
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["project_id"] == pre_created_pid


@pytest.mark.asyncio
async def test_init_with_unknown_project_id_returns_404(db_infra, redis_client_async):
    """Passing a project_id that doesn't exist in server.projects returns 404."""
    slug = f"ghost-{uuid.uuid4().hex[:8]}"
    fake_pid = str(uuid.uuid4())

    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/init",
                json={
                    "project_slug": slug,
                    "project_id": fake_pid,
                    "project_name": slug,
                    "human_name": "Ghost Agent",
                    "agent_type": "agent",
                },
            )
            assert resp.status_code == 404, resp.text
            assert "project_not_found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_init_with_project_id_second_agent_independent(db_infra, redis_client_async):
    """Adding a second agent to project A doesn't affect project B's alias pool."""
    slug = f"indep-{uuid.uuid4().hex[:8]}"
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    pid_a = await _pre_create_project(db_infra, slug=slug, tenant_id=tenant_a)
    pid_b = await _pre_create_project(db_infra, slug=slug, tenant_id=tenant_b)

    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Create two agents in project A
            for i in range(2):
                resp = await client.post(
                    "/v1/init",
                    json={
                        "project_slug": slug,
                        "project_id": pid_a,
                        "project_name": slug,
                        "human_name": f"Agent A{i+1}",
                        "agent_type": "agent",
                        "repo_origin": f"git@github.com:test/{slug}-a{i}.git",
                        "role": "agent",
                    },
                )
                assert resp.status_code == 200, resp.text

            # Now create first agent in project B — should still get first alias
            resp_b = await client.post(
                "/v1/init",
                json={
                    "project_slug": slug,
                    "project_id": pid_b,
                    "project_name": slug,
                    "human_name": "Agent B1",
                    "agent_type": "agent",
                    "repo_origin": f"git@github.com:test/{slug}-b.git",
                    "role": "agent",
                },
            )
            assert resp_b.status_code == 200, resp_b.text

            # B's first agent should get the first name prefix, unaffected by A's agents
            alias_b = resp_b.json()["alias"]
            # The first alias from CLASSIC_NAMES with "-agent" suffix
            assert alias_b.endswith("-agent"), f"Expected '-agent' suffix, got {alias_b!r}"
            # Verify it's the first name (not the third), proving pool independence
            from beadhub.names import CLASSIC_NAMES

            assert alias_b.startswith(
                CLASSIC_NAMES[0]
            ), f"Expected alias starting with {CLASSIC_NAMES[0]!r}, got {alias_b!r}"

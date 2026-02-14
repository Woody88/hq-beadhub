"""Tests for project policy storage and bootstrap."""

import json
import uuid
from pathlib import Path

import asyncpg
import pytest
from pgdbm import AsyncDatabaseManager
from pgdbm.errors import QueryError
from pgdbm.migrations import AsyncMigrationManager

from beadhub.routes.policies import (
    DEFAULT_POLICY_BUNDLE,
    activate_policy,
    create_policy_version,
    get_active_policy,
)


async def _setup_server_schema(db: AsyncDatabaseManager) -> None:
    """Apply server migrations to the test database."""
    root = Path(__file__).resolve().parents[1]
    migrations_path = root / "src" / "beadhub" / "migrations" / "server"

    manager = AsyncMigrationManager(
        db,
        migrations_path=str(migrations_path),
        module_name="beadhub-server-test",
    )
    await manager.apply_pending_migrations()


@pytest.mark.asyncio
async def test_project_policies_migration(test_db_with_schema):
    """Verify project_policies table is created with correct structure."""
    await _setup_server_schema(test_db_with_schema)

    # Create a project
    project_id = str(uuid.uuid4())
    await test_db_with_schema.execute(
        "INSERT INTO {{tables.projects}} (id, slug, name) VALUES ($1, $2, $3)",
        project_id,
        "test-project",
        "Test Project",
    )

    # Insert a policy
    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    result = await test_db_with_schema.fetch_one(
        """
        INSERT INTO {{tables.project_policies}} (project_id, version, bundle_json)
        VALUES ($1, $2, $3::jsonb)
        RETURNING policy_id, version, created_at, updated_at
        """,
        project_id,
        1,
        json.dumps(bundle),
    )

    assert result is not None
    assert result["version"] == 1
    assert result["created_at"] is not None
    assert result["updated_at"] is not None


@pytest.mark.asyncio
async def test_policy_version_unique_constraint(test_db_with_schema):
    """Verify version numbers are unique per project."""
    await _setup_server_schema(test_db_with_schema)

    project_id = str(uuid.uuid4())
    await test_db_with_schema.execute(
        "INSERT INTO {{tables.projects}} (id, slug, name) VALUES ($1, $2, $3)",
        project_id,
        "test-project",
        "Test Project",
    )

    bundle = {"invariants": [], "roles": {}, "adapters": {}}

    # Insert version 1
    await test_db_with_schema.execute(
        """
        INSERT INTO {{tables.project_policies}} (project_id, version, bundle_json)
        VALUES ($1, $2, $3::jsonb)
        """,
        project_id,
        1,
        json.dumps(bundle),
    )

    # Duplicate version should fail
    with pytest.raises(QueryError) as exc_info:
        await test_db_with_schema.execute(
            """
            INSERT INTO {{tables.project_policies}} (project_id, version, bundle_json)
            VALUES ($1, $2, $3::jsonb)
            """,
            project_id,
            1,
            json.dumps(bundle),
        )
    assert isinstance(exc_info.value.__cause__, asyncpg.UniqueViolationError)


@pytest.mark.asyncio
async def test_policy_version_unique_per_project(test_db_with_schema):
    """Verify same version number allowed in different projects."""
    await _setup_server_schema(test_db_with_schema)

    project_1 = str(uuid.uuid4())
    project_2 = str(uuid.uuid4())

    await test_db_with_schema.execute(
        "INSERT INTO {{tables.projects}} (id, slug) VALUES ($1, $2), ($3, $4)",
        project_1,
        "project-1",
        project_2,
        "project-2",
    )

    bundle = {"invariants": [], "roles": {}, "adapters": {}}

    # Version 1 in project 1
    await test_db_with_schema.execute(
        """
        INSERT INTO {{tables.project_policies}} (project_id, version, bundle_json)
        VALUES ($1, $2, $3::jsonb)
        """,
        project_1,
        1,
        json.dumps(bundle),
    )

    # Version 1 in project 2 should succeed
    await test_db_with_schema.execute(
        """
        INSERT INTO {{tables.project_policies}} (project_id, version, bundle_json)
        VALUES ($1, $2, $3::jsonb)
        """,
        project_2,
        1,
        json.dumps(bundle),
    )

    # Verify both exist
    count = await test_db_with_schema.fetch_value(
        "SELECT COUNT(*) FROM {{tables.project_policies}} WHERE version = 1"
    )
    assert count == 2


@pytest.mark.asyncio
async def test_active_policy_fk(test_db_with_schema):
    """Verify active_policy_id FK works correctly."""
    await _setup_server_schema(test_db_with_schema)

    project_id = str(uuid.uuid4())
    await test_db_with_schema.execute(
        "INSERT INTO {{tables.projects}} (id, slug) VALUES ($1, $2)",
        project_id,
        "test-project",
    )

    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    policy = await test_db_with_schema.fetch_one(
        """
        INSERT INTO {{tables.project_policies}} (project_id, version, bundle_json)
        VALUES ($1, $2, $3::jsonb)
        RETURNING policy_id
        """,
        project_id,
        1,
        json.dumps(bundle),
    )

    # Set active policy
    await test_db_with_schema.execute(
        "UPDATE {{tables.projects}} SET active_policy_id = $2 WHERE id = $1",
        project_id,
        policy["policy_id"],
    )

    # Verify it was set
    result = await test_db_with_schema.fetch_one(
        "SELECT active_policy_id FROM {{tables.projects}} WHERE id = $1",
        project_id,
    )
    assert result["active_policy_id"] == policy["policy_id"]


@pytest.mark.asyncio
async def test_policy_cascade_on_project_delete(test_db_with_schema):
    """Verify policies are deleted when project is deleted."""
    await _setup_server_schema(test_db_with_schema)

    project_id = str(uuid.uuid4())
    await test_db_with_schema.execute(
        "INSERT INTO {{tables.projects}} (id, slug) VALUES ($1, $2)",
        project_id,
        "test-project",
    )

    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    await test_db_with_schema.execute(
        """
        INSERT INTO {{tables.project_policies}} (project_id, version, bundle_json)
        VALUES ($1, $2, $3::jsonb)
        """,
        project_id,
        1,
        json.dumps(bundle),
    )

    # Delete project
    await test_db_with_schema.execute(
        "DELETE FROM {{tables.projects}} WHERE id = $1",
        project_id,
    )

    # Policies should be gone
    count = await test_db_with_schema.fetch_value(
        "SELECT COUNT(*) FROM {{tables.project_policies}} WHERE project_id = $1",
        project_id,
    )
    assert count == 0


@pytest.mark.asyncio
async def test_create_policy_version(db_infra):
    """Test create_policy_version helper function."""
    server_db = db_infra.get_manager("server")

    # Create a project
    project = await server_db.fetch_one(
        """
        INSERT INTO {{tables.projects}} (slug, name)
        VALUES ($1, $2)
        RETURNING id
        """,
        "test-project",
        "Test Project",
    )
    project_id = str(project["id"])

    # Create first version
    bundle = {"invariants": [{"id": "test", "title": "Test", "body_md": "Test body"}]}
    policy_v1 = await create_policy_version(
        server_db,
        project_id=project_id,
        base_policy_id=None,
        bundle=bundle,
        created_by_workspace_id=None,
    )

    assert policy_v1.version == 1
    assert policy_v1.project_id == project_id
    assert len(policy_v1.bundle.invariants) == 1

    # Activate v1 so that v2 can reference it as base
    await activate_policy(server_db, project_id=project_id, policy_id=policy_v1.policy_id)

    # Create second version
    policy_v2 = await create_policy_version(
        server_db,
        project_id=project_id,
        base_policy_id=policy_v1.policy_id,
        bundle=bundle,
        created_by_workspace_id=None,
    )

    assert policy_v2.version == 2


@pytest.mark.asyncio
async def test_create_policy_version_nonexistent_project(db_infra):
    """Test create_policy_version fails for nonexistent project."""
    from fastapi import HTTPException

    server_db = db_infra.get_manager("server")

    with pytest.raises(HTTPException) as exc_info:
        await create_policy_version(
            server_db,
            project_id=str(uuid.uuid4()),
            base_policy_id=None,
            bundle={},
            created_by_workspace_id=None,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_activate_policy(db_infra):
    """Test activate_policy helper function."""
    server_db = db_infra.get_manager("server")

    # Create a project
    project = await server_db.fetch_one(
        """
        INSERT INTO {{tables.projects}} (slug, name)
        VALUES ($1, $2)
        RETURNING id
        """,
        "test-project",
        "Test Project",
    )
    project_id = str(project["id"])

    # Create a policy
    policy = await create_policy_version(
        server_db,
        project_id=project_id,
        base_policy_id=None,
        bundle={"invariants": []},
        created_by_workspace_id=None,
    )

    # Activate it
    result = await activate_policy(
        server_db,
        project_id=project_id,
        policy_id=policy.policy_id,
    )
    assert result is True

    # Verify it's active
    row = await server_db.fetch_one(
        "SELECT active_policy_id FROM {{tables.projects}} WHERE id = $1",
        project_id,
    )
    assert str(row["active_policy_id"]) == policy.policy_id


@pytest.mark.asyncio
async def test_activate_policy_wrong_project(db_infra):
    """Test activate_policy fails for policy from different project."""
    from fastapi import HTTPException

    server_db = db_infra.get_manager("server")

    # Create two projects
    project_1 = await server_db.fetch_one(
        "INSERT INTO {{tables.projects}} (slug) VALUES ($1) RETURNING id",
        "project-1",
    )
    project_2 = await server_db.fetch_one(
        "INSERT INTO {{tables.projects}} (slug) VALUES ($1) RETURNING id",
        "project-2",
    )

    # Create policy in project 1
    policy = await create_policy_version(
        server_db,
        project_id=str(project_1["id"]),
        base_policy_id=None,
        bundle={},
        created_by_workspace_id=None,
    )

    # Try to activate in project 2
    with pytest.raises(HTTPException) as exc_info:
        await activate_policy(
            server_db,
            project_id=str(project_2["id"]),
            policy_id=policy.policy_id,
        )
    assert exc_info.value.status_code == 400
    assert "does not belong to this project" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_active_policy_bootstrap(db_infra):
    """Test get_active_policy bootstraps default policy when none exists."""
    server_db = db_infra.get_manager("server")

    # Create a project with no policy
    project = await server_db.fetch_one(
        "INSERT INTO {{tables.projects}} (slug) VALUES ($1) RETURNING id",
        "test-project",
    )
    project_id = str(project["id"])

    # Get active policy - should bootstrap
    policy = await get_active_policy(server_db, project_id)

    assert policy is not None
    assert policy.version == 1
    assert len(policy.bundle.invariants) == len(DEFAULT_POLICY_BUNDLE["invariants"])
    assert "coordinator" in policy.bundle.roles
    assert "developer" in policy.bundle.roles
    assert "reviewer" in policy.bundle.roles

    # Verify it's now set as active
    row = await server_db.fetch_one(
        "SELECT active_policy_id FROM {{tables.projects}} WHERE id = $1",
        project_id,
    )
    assert str(row["active_policy_id"]) == policy.policy_id


@pytest.mark.asyncio
async def test_get_active_policy_no_bootstrap(db_infra):
    """Test get_active_policy returns None when bootstrap disabled."""
    server_db = db_infra.get_manager("server")

    project = await server_db.fetch_one(
        "INSERT INTO {{tables.projects}} (slug) VALUES ($1) RETURNING id",
        "test-project",
    )
    project_id = str(project["id"])

    # Get without bootstrap
    policy = await get_active_policy(server_db, project_id, bootstrap_if_missing=False)
    assert policy is None


@pytest.mark.asyncio
async def test_get_active_policy_existing(db_infra):
    """Test get_active_policy returns existing active policy."""
    server_db = db_infra.get_manager("server")

    project = await server_db.fetch_one(
        "INSERT INTO {{tables.projects}} (slug) VALUES ($1) RETURNING id",
        "test-project",
    )
    project_id = str(project["id"])

    # Create and activate a custom policy
    custom_bundle = {
        "invariants": [{"id": "custom", "title": "Custom", "body_md": "Custom policy"}],
        "roles": {},
        "adapters": {},
    }
    policy = await create_policy_version(
        server_db,
        project_id=project_id,
        base_policy_id=None,
        bundle=custom_bundle,
        created_by_workspace_id=None,
    )
    await activate_policy(server_db, project_id=project_id, policy_id=policy.policy_id)

    # Get should return our custom policy, not bootstrap
    fetched = await get_active_policy(server_db, project_id)

    assert fetched is not None
    assert fetched.policy_id == policy.policy_id
    assert len(fetched.bundle.invariants) == 1
    assert fetched.bundle.invariants[0]["id"] == "custom"


@pytest.mark.asyncio
async def test_policy_project_isolation(db_infra):
    """Test policies are properly isolated between projects."""
    server_db = db_infra.get_manager("server")

    # Create two projects
    project_1 = await server_db.fetch_one(
        "INSERT INTO {{tables.projects}} (slug) VALUES ($1) RETURNING id",
        "project-1",
    )
    project_2 = await server_db.fetch_one(
        "INSERT INTO {{tables.projects}} (slug) VALUES ($1) RETURNING id",
        "project-2",
    )

    # Bootstrap policies for both
    policy_1 = await get_active_policy(server_db, str(project_1["id"]))
    policy_2 = await get_active_policy(server_db, str(project_2["id"]))

    # They should be different policies
    assert policy_1.policy_id != policy_2.policy_id
    assert policy_1.project_id != policy_2.project_id

    # Cross-project activation should fail
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await activate_policy(
            server_db,
            project_id=str(project_1["id"]),
            policy_id=policy_2.policy_id,
        )


# Integration tests for GET /v1/policies/active endpoint


def _init_project(beadhub_server: str, slug: str) -> tuple[str, str]:
    """Create a project/agent/api_key in aweb, then register a BeadHub workspace."""
    import uuid

    import httpx

    aweb_resp = httpx.post(
        f"{beadhub_server}/v1/init",
        json={
            "project_slug": slug,
            "project_name": slug,
            "alias": f"init-{uuid.uuid4().hex[:8]}",
            "human_name": "Init User",
            "agent_type": "agent",
        },
        timeout=10.0,
    )
    assert aweb_resp.status_code == 200, aweb_resp.text
    api_key = aweb_resp.json()["api_key"]

    repo_origin = f"git@github.com:test/{slug}-{uuid.uuid4().hex[:8]}.git"
    reg = httpx.post(
        f"{beadhub_server}/v1/workspaces/register",
        json={"repo_origin": repo_origin, "role": "agent"},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )
    assert reg.status_code == 200, reg.text
    project_id = reg.json()["project_id"]
    return project_id, api_key


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_get_active_policy_endpoint_happy_path(beadhub_server):
    """Test GET /v1/policies/active returns active policy."""
    import httpx

    project_id, api_key = _init_project(beadhub_server, "test-policy-project")

    # Get active policy
    resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["project_id"] == project_id
    assert data["version"] == 1
    assert "invariants" in data
    assert "roles" in data
    assert "coordinator" in data["roles"]
    assert "developer" in data["roles"]
    assert "reviewer" in data["roles"]

    # Check ETag header is present
    assert "ETag" in resp.headers


def test_get_active_policy_endpoint_with_role_selection(beadhub_server):
    """Test GET /v1/policies/active with role selection."""
    import httpx

    project_id, api_key = _init_project(beadhub_server, "test-role-project")

    # Get with role selection
    resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
        params={"role": "coordinator"},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "selected_role" in data
    assert data["selected_role"]["role"] == "coordinator"
    assert data["selected_role"]["title"] == "Coordinator"
    # All roles should still be present
    assert len(data["roles"]) == len(DEFAULT_POLICY_BUNDLE["roles"])


def test_get_active_policy_endpoint_only_selected(beadhub_server):
    """Test GET /v1/policies/active with only_selected=true."""
    import httpx

    project_id, api_key = _init_project(beadhub_server, "test-only-selected")

    # Get with only_selected
    resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
        params={"role": "reviewer", "only_selected": "true"},
    )
    assert resp.status_code == 200

    data = resp.json()
    # Only reviewer role should be present
    assert len(data["roles"]) == 1
    assert "reviewer" in data["roles"]
    assert data["selected_role"]["role"] == "reviewer"


def test_get_active_policy_endpoint_invalid_role(beadhub_server):
    """Test GET /v1/policies/active with invalid role returns 400."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-invalid-role")

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
        params={"role": "nonexistent"},
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]
    assert "Available roles" in resp.json()["detail"]


def test_get_active_policy_endpoint_only_selected_requires_role(beadhub_server):
    """Test only_selected=true without role returns 400."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-only-selected-no-role")

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
        params={"only_selected": "true"},
    )
    assert resp.status_code == 400
    assert "requires a role parameter" in resp.json()["detail"]


def test_get_active_policy_endpoint_conditional_get_304(beadhub_server):
    """Test conditional GET returns 304 when ETag matches."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-etag")

    # First request to get ETag
    resp1 = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
    )
    assert resp1.status_code == 200
    etag = resp1.headers["ETag"]

    # Second request with If-None-Match
    resp2 = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers={**_auth_headers(api_key), "If-None-Match": etag},
    )
    assert resp2.status_code == 304


def test_get_active_policy_endpoint_missing_project_id(beadhub_server):
    """Test GET /v1/policies/active without auth returns 401."""
    import httpx

    resp = httpx.get(f"{beadhub_server}/v1/policies/active")
    assert resp.status_code == 401


def test_get_active_policy_endpoint_invalid_project_id(beadhub_server):
    """Test GET /v1/policies/active with invalid Bearer token returns 401."""
    import httpx

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers={"Authorization": "Bearer not-a-valid-key"},
    )
    assert resp.status_code == 401


# Integration tests for admin endpoints (POST /v1/policies and POST /v1/policies/{id}/activate)


def test_create_policy_endpoint(beadhub_server):
    """Test POST /v1/policies creates a new policy version."""
    import httpx

    project_id, api_key = _init_project(beadhub_server, "test-create-policy")

    # Create a new policy
    bundle = {
        "invariants": [{"id": "test", "title": "Test", "body_md": "Test invariant"}],
        "roles": {"tester": {"title": "Tester", "playbook_md": "Test playbook"}},
        "adapters": {},
    }
    resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["project_id"] == project_id
    assert data["version"] >= 1
    assert data["created"] is True
    assert "policy_id" in data


def test_create_policy_increments_version(beadhub_server):
    """Test POST /v1/policies increments version number."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-version-increment")

    bundle = {"invariants": [], "roles": {}, "adapters": {}}

    # Create first policy
    resp1 = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    version1 = resp1.json()["version"]

    # Create second policy
    resp2 = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    version2 = resp2.json()["version"]

    assert version2 == version1 + 1


def test_activate_policy_endpoint(beadhub_server):
    """Test POST /v1/policies/{id}/activate sets active policy."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-activate-policy")

    # Create a policy
    bundle = {
        "invariants": [],
        "roles": {"admin": {"title": "Admin", "playbook_md": ""}},
        "adapters": {},
    }
    create_resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    policy_id = create_resp.json()["policy_id"]

    # Activate it
    resp = httpx.post(
        f"{beadhub_server}/v1/policies/{policy_id}/activate",
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["activated"] is True
    assert data["active_policy_id"] == policy_id

    # Verify it's now active
    get_resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
    )
    assert get_resp.json()["policy_id"] == policy_id


def test_activate_policy_cross_project_rejected(beadhub_server):
    """Test activating a policy from another project is rejected."""
    import httpx

    project1_id, api_key_1 = _init_project(beadhub_server, "test-cross-project-1")
    project2_id, api_key_2 = _init_project(beadhub_server, "test-cross-project-2")

    # Create policy in project 1
    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    create_resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key_1),
        json={"bundle": bundle},
    )
    policy_id = create_resp.json()["policy_id"]

    # Try to activate in project 2
    resp = httpx.post(
        f"{beadhub_server}/v1/policies/{policy_id}/activate",
        headers=_auth_headers(api_key_2),
    )
    assert resp.status_code == 400
    assert "does not belong to this project" in resp.json()["detail"]


def test_activate_nonexistent_policy(beadhub_server):
    """Test activating a nonexistent policy returns 404."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-nonexistent-policy")

    resp = httpx.post(
        f"{beadhub_server}/v1/policies/00000000-0000-0000-0000-000000000000/activate",
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 404


def test_create_policy_missing_project_id(beadhub_server):
    """Test POST /v1/policies without auth returns 401."""
    import httpx

    resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        json={"bundle": {"invariants": [], "roles": {}, "adapters": {}}},
    )
    assert resp.status_code == 401


# Integration tests for GET /v1/policies/history endpoint


def test_list_policy_history(beadhub_server):
    """Test GET /v1/policies/history returns policy versions."""
    import httpx

    project_id, api_key = _init_project(beadhub_server, "test-policy-history")

    # Create multiple policy versions
    bundle1 = {
        "invariants": [{"id": "v1", "title": "V1", "body_md": ""}],
        "roles": {},
        "adapters": {},
    }
    bundle2 = {
        "invariants": [{"id": "v2", "title": "V2", "body_md": ""}],
        "roles": {},
        "adapters": {},
    }
    bundle3 = {
        "invariants": [{"id": "v3", "title": "V3", "body_md": ""}],
        "roles": {},
        "adapters": {},
    }

    resp1 = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle1},
    )
    resp2 = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle2},
    )
    resp3 = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle3},
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 200

    # Get history
    resp = httpx.get(
        f"{beadhub_server}/v1/policies/history",
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "policies" in data
    # /v1/init seeds a default policy for new projects. This test creates 3
    # additional versions, so we expect 4 total.
    assert len(data["policies"]) == 4

    # Should be ordered by version descending (newest first)
    versions = [p["version"] for p in data["policies"]]
    assert versions == sorted(versions, reverse=True)

    # Each policy should have required fields
    for policy in data["policies"]:
        assert "policy_id" in policy
        assert "version" in policy
        assert "created_at" in policy
        assert "is_active" in policy


def test_list_policy_history_marks_active(beadhub_server):
    """Test GET /v1/policies/history marks the active policy."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-history-active-marker")

    # Create two versions
    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    resp2 = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    policy2_id = resp2.json()["policy_id"]

    # Activate the second one
    httpx.post(
        f"{beadhub_server}/v1/policies/{policy2_id}/activate",
        headers=_auth_headers(api_key),
    )

    # Get history
    resp = httpx.get(
        f"{beadhub_server}/v1/policies/history",
        headers=_auth_headers(api_key),
    )
    data = resp.json()

    active_count = sum(1 for p in data["policies"] if p["is_active"])
    assert active_count == 1

    active_policy = next(p for p in data["policies"] if p["is_active"])
    assert active_policy["policy_id"] == policy2_id


def test_list_policy_history_limit(beadhub_server):
    """Test GET /v1/policies/history respects limit parameter."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-history-limit")

    # Create 5 policies
    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    for _ in range(5):
        httpx.post(
            f"{beadhub_server}/v1/policies",
            headers=_auth_headers(api_key),
            json={"bundle": bundle},
        )

    # Get with limit=2
    resp = httpx.get(
        f"{beadhub_server}/v1/policies/history",
        headers=_auth_headers(api_key),
        params={"limit": 2},
    )
    data = resp.json()

    assert len(data["policies"]) == 2
    # Should be newest two versions
    # /v1/init seeds version 1, so 5 created policies are versions 2..6.
    assert data["policies"][0]["version"] == 6
    assert data["policies"][1]["version"] == 5


def test_list_policy_history_empty_project(beadhub_server):
    """Test GET /v1/policies/history for a newly-created project."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-history-empty")

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/history",
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 200

    data = resp.json()
    # New projects get a seeded default policy.
    assert len(data["policies"]) == 1
    assert data["policies"][0]["version"] == 1
    assert data["policies"][0]["is_active"] is True


def test_list_policy_history_missing_project_id(beadhub_server):
    """Test GET /v1/policies/history without auth returns 401."""
    import httpx

    resp = httpx.get(f"{beadhub_server}/v1/policies/history")
    assert resp.status_code == 401


# GET /v1/policies/{policy_id} tests


def test_get_policy_by_id(beadhub_server):
    """Test GET /v1/policies/{policy_id} returns the requested policy."""
    import httpx

    project_id, api_key = _init_project(beadhub_server, "test-get-policy-by-id")

    bundle = {
        "invariants": [{"id": "test.inv", "title": "Test", "body_md": "Test body"}],
        "roles": {"tester": {"title": "Tester", "playbook_md": "Test playbook"}},
        "adapters": {},
    }
    create_resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    assert create_resp.status_code == 200
    policy_id = create_resp.json()["policy_id"]

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/{policy_id}",
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["policy_id"] == policy_id
    assert data["project_id"] == project_id
    assert len(data["invariants"]) == 1
    assert data["invariants"][0]["id"] == "test.inv"
    assert "tester" in data["roles"]


def test_reset_policy_to_default(beadhub_server):
    """Test POST /v1/policies/reset creates+activates DEFAULT_POLICY_BUNDLE as new version."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-policy-reset-default")

    # Create a custom policy and activate it so we can observe reset behavior.
    bundle = {
        "invariants": [{"id": "custom", "title": "Custom", "body_md": "Custom policy"}],
        "roles": {},
        "adapters": {},
    }
    create_resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    assert create_resp.status_code == 200
    custom_policy_id = create_resp.json()["policy_id"]

    activate_resp = httpx.post(
        f"{beadhub_server}/v1/policies/{custom_policy_id}/activate",
        headers=_auth_headers(api_key),
    )
    assert activate_resp.status_code == 200

    # Reset to default (creates a new version and activates it).
    reset_resp = httpx.post(
        f"{beadhub_server}/v1/policies/reset",
        headers=_auth_headers(api_key),
    )
    assert reset_resp.status_code == 200
    reset_data = reset_resp.json()
    assert reset_data["reset"] is True
    assert reset_data["active_policy_id"]
    assert reset_data["version"] >= 1

    # Active policy should now include the seeded roles (coordinator, etc).
    active_resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
    )
    assert active_resp.status_code == 200
    active_data = active_resp.json()
    assert active_data["policy_id"] == reset_data["active_policy_id"]
    assert "coordinator" in active_data["roles"]
    assert "developer" in active_data["roles"]
    assert "reviewer" in active_data["roles"]


def test_get_policy_by_id_missing_project_id(beadhub_server):
    """Test GET /v1/policies/{policy_id} without auth returns 401."""
    import httpx

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/00000000-0000-0000-0000-000000000000",
    )
    assert resp.status_code == 401


def test_get_policy_by_id_cross_project_rejected(beadhub_server):
    """Test GET /v1/policies/{policy_id} rejects cross-project access."""
    import httpx

    _project1_id, api_key_1 = _init_project(beadhub_server, "test-get-cross-1")
    _project2_id, api_key_2 = _init_project(beadhub_server, "test-get-cross-2")

    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    create_resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key_1),
        json={"bundle": bundle},
    )
    policy_id = create_resp.json()["policy_id"]

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/{policy_id}",
        headers=_auth_headers(api_key_2),
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_policy_by_id_nonexistent(beadhub_server):
    """Test GET /v1/policies/{policy_id} with nonexistent ID returns 404."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-get-nonexistent")

    resp = httpx.get(
        f"{beadhub_server}/v1/policies/00000000-0000-0000-0000-000000000000",
        headers=_auth_headers(api_key),
    )
    assert resp.status_code == 404


# Optimistic concurrency tests


def test_create_policy_with_stale_base_policy_id_returns_409(beadhub_server):
    """POST /v1/policies with base_policy_id that doesn't match active returns 409."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-optimistic-conflict")

    # Get the bootstrapped active policy
    active_resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
    )
    assert active_resp.status_code == 200
    original_policy_id = active_resp.json()["policy_id"]

    # Agent A reads the active policy and creates a new version based on it
    bundle_a = {
        "invariants": [{"id": "a", "title": "A", "body_md": ""}],
        "roles": {},
        "adapters": {},
    }
    resp_a = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle_a, "base_policy_id": original_policy_id},
    )
    assert resp_a.status_code == 200
    policy_a_id = resp_a.json()["policy_id"]

    # Agent A activates their policy
    httpx.post(
        f"{beadhub_server}/v1/policies/{policy_a_id}/activate",
        headers=_auth_headers(api_key),
    )

    # Agent B tries to create based on the ORIGINAL (now stale) policy
    bundle_b = {
        "invariants": [{"id": "b", "title": "B", "body_md": ""}],
        "roles": {},
        "adapters": {},
    }
    resp_b = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle_b, "base_policy_id": original_policy_id},
    )
    assert resp_b.status_code == 409
    assert "conflict" in resp_b.json()["detail"].lower()


def test_create_policy_with_matching_base_policy_id_succeeds(beadhub_server):
    """POST /v1/policies with base_policy_id matching active succeeds."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-optimistic-match")

    # Get the bootstrapped active policy
    active_resp = httpx.get(
        f"{beadhub_server}/v1/policies/active",
        headers=_auth_headers(api_key),
    )
    active_policy_id = active_resp.json()["policy_id"]

    # Create with matching base_policy_id
    bundle = {
        "invariants": [{"id": "ok", "title": "OK", "body_md": ""}],
        "roles": {},
        "adapters": {},
    }
    resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle, "base_policy_id": active_policy_id},
    )
    assert resp.status_code == 200


def test_create_policy_without_base_policy_id_skips_check(beadhub_server):
    """POST /v1/policies without base_policy_id always succeeds (backward compatible)."""
    import httpx

    _project_id, api_key = _init_project(beadhub_server, "test-optimistic-skip")

    # Create without base_policy_id — should always work
    bundle = {"invariants": [], "roles": {}, "adapters": {}}
    resp = httpx.post(
        f"{beadhub_server}/v1/policies",
        headers=_auth_headers(api_key),
        json={"bundle": bundle},
    )
    assert resp.status_code == 200

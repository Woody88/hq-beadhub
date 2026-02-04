import json
import logging
import uuid

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from beadhub.api import create_app

logger = logging.getLogger(__name__)

TEST_REDIS_URL = "redis://localhost:6379/15"
TEST_REPO_ORIGIN = "git@github.com:anthropic/beadhub.git"


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _jsonl(*rows: dict) -> str:
    return "\n".join(json.dumps(r) for r in rows) + "\n"


@pytest.mark.asyncio
async def test_bdh_command_requires_workspace_and_returns_claims(db_infra, init_workspace):
    redis = await Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        logger.warning("Redis is not available; skipping test", exc_info=True)
        pytest.skip("Redis is not available")
    await redis.flushdb()

    try:
        app = create_app(db_infra=db_infra, redis=redis, serve_frontend=False)
        async with LifespanManager(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                init = await init_workspace(
                    client,
                    project_slug=f"bdh-{uuid.uuid4().hex[:8]}",
                    repo_origin=TEST_REPO_ORIGIN,
                    alias="alice-agent",
                    human_name="Alice",
                    role="agent",
                )

                resp = await client.post(
                    "/v1/bdh/command",
                    headers=auth_headers(init["api_key"]),
                    json={
                        "workspace_id": init["workspace_id"],
                        "repo_id": init["repo_id"],
                        "alias": init["alias"],
                        "human_name": init["human_name"],
                        "repo_origin": TEST_REPO_ORIGIN,
                        "role": "agent",
                        "command_line": "ready",
                    },
                )
                assert resp.status_code == 200, resp.text
                data = resp.json()
                assert data["approved"] is True
                assert data["context"]["beads_in_progress"] == []
    except Exception:
        logger.exception("test_bdh_command_requires_workspace_and_returns_claims failed")
        raise
    finally:
        await redis.flushdb()
        await redis.aclose()


@pytest.mark.asyncio
async def test_bdh_sync_sets_and_clears_claims(db_infra, init_workspace):
    redis = await Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        logger.warning("Redis is not available; skipping test", exc_info=True)
        pytest.skip("Redis is not available")
    await redis.flushdb()

    try:
        app = create_app(db_infra=db_infra, redis=redis, serve_frontend=False)
        async with LifespanManager(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                init = await init_workspace(
                    client,
                    project_slug=f"bdh-{uuid.uuid4().hex[:8]}",
                    repo_origin=TEST_REPO_ORIGIN,
                    alias="alice-agent",
                    human_name="Alice",
                    role="agent",
                )

                # Full sync after claiming a bead (bdh does full on first run).
                resp = await client.post(
                    "/v1/bdh/sync",
                    headers=auth_headers(init["api_key"]),
                    json={
                        "workspace_id": init["workspace_id"],
                        "repo_id": init["repo_id"],
                        "alias": init["alias"],
                        "human_name": init["human_name"],
                        "repo_origin": TEST_REPO_ORIGIN,
                        "role": "agent",
                        "sync_mode": "full",
                        "issues_jsonl": _jsonl(
                            {"id": "bd-1", "title": "t", "status": "in_progress"}
                        ),
                        "command_line": "update bd-1 --status in_progress",
                    },
                )
                assert resp.status_code == 200, resp.text

                claims = await client.get("/v1/claims", headers=auth_headers(init["api_key"]))
                assert claims.status_code == 200
                claim_list = claims.json()["claims"]
                assert len(claim_list) == 1
                assert claim_list[0]["bead_id"] == "bd-1"
                assert claim_list[0]["workspace_id"] == init["workspace_id"]

                # Incremental sync clears claim when closing.
                resp = await client.post(
                    "/v1/bdh/sync",
                    headers=auth_headers(init["api_key"]),
                    json={
                        "workspace_id": init["workspace_id"],
                        "repo_id": init["repo_id"],
                        "alias": init["alias"],
                        "human_name": init["human_name"],
                        "repo_origin": TEST_REPO_ORIGIN,
                        "role": "agent",
                        "sync_mode": "incremental",
                        "changed_issues": _jsonl({"id": "bd-1", "title": "t", "status": "closed"}),
                        "deleted_ids": [],
                        "command_line": "close bd-1",
                    },
                )
                assert resp.status_code == 200, resp.text

                claims = await client.get("/v1/claims", headers=auth_headers(init["api_key"]))
                assert claims.status_code == 200
                assert claims.json()["claims"] == []
    except Exception:
        logger.exception("test_bdh_sync_sets_and_clears_claims failed")
        raise
    finally:
        await redis.flushdb()
        await redis.aclose()


@pytest.mark.asyncio
async def test_bdh_command_returns_410_when_workspace_deleted(db_infra, init_workspace):
    redis = await Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        await redis.ping()
    except Exception:
        logger.warning("Redis is not available; skipping test", exc_info=True)
        pytest.skip("Redis is not available")
    await redis.flushdb()

    try:
        app = create_app(db_infra=db_infra, redis=redis, serve_frontend=False)
        async with LifespanManager(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                init = await init_workspace(
                    client,
                    project_slug=f"bdh-{uuid.uuid4().hex[:8]}",
                    repo_origin=TEST_REPO_ORIGIN,
                    alias="alice-agent",
                    human_name="Alice",
                    role="agent",
                )

                # Soft-delete workspace.
                delete_resp = await client.delete(
                    f"/v1/workspaces/{init['workspace_id']}",
                    headers=auth_headers(init["api_key"]),
                )
                assert delete_resp.status_code == 200, delete_resp.text

                resp = await client.post(
                    "/v1/bdh/command",
                    headers=auth_headers(init["api_key"]),
                    json={
                        "workspace_id": init["workspace_id"],
                        "repo_id": init["repo_id"],
                        "alias": init["alias"],
                        "human_name": init["human_name"],
                        "repo_origin": TEST_REPO_ORIGIN,
                        "role": "agent",
                        "command_line": "ready",
                    },
                )
                assert resp.status_code == 410, resp.text
    except Exception:
        logger.exception("test_bdh_command_returns_410_when_workspace_deleted failed")
        raise
    finally:
        await redis.flushdb()
        await redis.aclose()

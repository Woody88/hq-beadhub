import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from beadhub.api import create_app

from .conftest import auth_headers


@pytest.mark.asyncio
async def test_suggest_name_prefix_uses_authenticated_project_even_if_repo_registered_elsewhere(
    db_infra, redis_client_async
):
    app = create_app(db_infra=db_infra, redis=redis_client_async, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Project A registers repo-a and consumes the "alice" classic prefix.
            resp_a = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-snp-project-a",
                    "project_name": "test-snp-project-a",
                    "repo_origin": "git@github.com:test/snp-repo-a.git",
                    "alias": "alice-agent",
                    "human_name": "Init User",
                    "role": "agent",
                },
            )
            assert resp_a.status_code == 200, resp_a.text

            # Project B exists (with a different repo) and authenticates with its own API key.
            resp_b = await client.post(
                "/v1/init",
                json={
                    "project_slug": "test-snp-project-b",
                    "project_name": "test-snp-project-b",
                    "repo_origin": "git@github.com:test/snp-repo-b.git",
                    "alias": "zz-agent",
                    "human_name": "Init User",
                    "role": "agent",
                },
            )
            assert resp_b.status_code == 200, resp_b.text
            b = resp_b.json()
            api_key_b = b["api_key"]
            project_id_b = b["project_id"]

            # Unauthenticated call should use the repo's owning project (project A) and suggest "bob".
            unauth = await client.post(
                "/v1/workspaces/suggest-name-prefix",
                json={"origin_url": "git@github.com:test/snp-repo-a.git"},
            )
            assert unauth.status_code == 200, unauth.text
            unauth_data = unauth.json()
            assert unauth_data["project_slug"] == "test-snp-project-a"
            assert unauth_data["name_prefix"] == "bob"

            # Authenticated to project B, suggestion must be scoped to project B (no cross-project leak),
            # even though the repo is currently registered in project A.
            auth = await client.post(
                "/v1/workspaces/suggest-name-prefix",
                json={"origin_url": "git@github.com:test/snp-repo-a.git"},
                headers=auth_headers(api_key_b),
            )
            assert auth.status_code == 200, auth.text
            auth_data = auth.json()
            assert auth_data["project_id"] == project_id_b
            assert auth_data["project_slug"] == "test-snp-project-b"
            assert auth_data["canonical_origin"] == "github.com/test/snp-repo-a"
            assert auth_data["repo_id"] == ""
            assert auth_data["name_prefix"] == "alice"


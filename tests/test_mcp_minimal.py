"""Tests for BeadHub MCP minimal surface (clean-slate split)."""

import json

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from beadhub.api import create_app


def _extract_payload(response):
    body = response.json()
    text = body["result"]["content"][0]["text"]
    return json.loads(text)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


@pytest.mark.asyncio
async def test_mcp_register_agent_and_list_agents(db_infra, async_redis, init_workspace):
    app = create_app(db_infra=db_infra, redis=async_redis, serve_frontend=False)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            init = await init_workspace(
                client,
                project_slug="mcp-minimal",
                repo_origin="git@github.com:test/mcp-minimal.git",
                alias="agent-one",
                human_name="Test Human",
            )
            api_key = init["api_key"]
            workspace_id = init["workspace_id"]

            register_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "register_agent",
                    "arguments": {
                        "workspace_id": workspace_id,
                        "alias": "agent-one",
                        "human_name": "Test Human",
                        "program": "codex-cli",
                        "model": "gpt-5.1",
                    },
                },
            }
            reg = await client.post("/mcp", json=register_req, headers=_auth_headers(api_key))
            assert reg.status_code == 200, reg.text
            assert _extract_payload(reg)["ok"] is True

            list_req = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_agents", "arguments": {"workspace_id": workspace_id}},
            }
            listed = await client.post("/mcp", json=list_req, headers=_auth_headers(api_key))
            assert listed.status_code == 200, listed.text
            agents = _extract_payload(listed)["agents"]
            assert any(a.get("alias") == "agent-one" for a in agents)

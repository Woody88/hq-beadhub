import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from aweb.db import DatabaseInfra as AwebDatabaseInfra
from pgdbm.fixtures.conftest import *  # noqa: F401,F403
from pgdbm.testing import AsyncTestDatabase, DatabaseTestConfig
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from beadhub.db import DatabaseInfra

from .db_utils import build_database_url

logger = logging.getLogger(__name__)

TEST_REDIS_URL = os.getenv("BEADHUB_TEST_REDIS_URL", "redis://localhost:6379/15")
TEST_SERVER_PORT = 18765  # Use non-standard port for test server
TEST_SERVER_URL = f"http://localhost:{TEST_SERVER_PORT}"


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


@pytest_asyncio.fixture
async def init_workspace():
    async def _init(
        client: httpx.AsyncClient,
        *,
        project_slug: str | None,
        repo_origin: str,
        alias: str,
        human_name: str = "Test Human",
        role: str = "agent",
        hostname: str | None = None,
        workspace_path: str | None = None,
    ) -> dict:
        if not project_slug:
            raise ValueError("project_slug is required in clean-slate split tests")

        # 1) Create identity/auth via the embedded aweb protocol implementation.
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
        aweb_data = aweb_resp.json()
        api_key = aweb_data["api_key"]
        assert api_key.startswith("aw_sk_")

        # 2) Register BeadHub workspace/repo state for that identity.
        beadhub_payload = {
            "repo_origin": repo_origin,
            "hostname": hostname,
            "workspace_path": workspace_path,
            "role": role,
        }
        beadhub_payload = {k: v for k, v in beadhub_payload.items() if v is not None}
        resp = await client.post(
            "/v1/workspaces/register",
            json=beadhub_payload,
            headers=auth_headers(api_key),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        data["api_key"] = api_key
        return data

    return _init


@pytest.fixture
def redis_client():
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except Exception:
        pytest.skip("Redis is not available")
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


@pytest.fixture
def set_redis_env(monkeypatch, redis_client):
    monkeypatch.setenv("REDIS_URL", TEST_REDIS_URL)


@pytest_asyncio.fixture
async def async_redis() -> AsyncGenerator[AsyncRedis, None]:
    """Fixture providing async Redis client for async tests."""
    try:
        redis = await AsyncRedis.from_url(TEST_REDIS_URL, decode_responses=True)
        await redis.ping()
    except Exception:
        pytest.skip("Redis is not available")
    await redis.flushdb()
    yield redis
    await redis.flushdb()
    await redis.aclose()


@pytest_asyncio.fixture
async def redis_client_async(async_redis: AsyncRedis) -> AsyncRedis:
    """Alias for async_redis for compatibility with tests using this name."""
    return async_redis


@pytest_asyncio.fixture
async def db_infra(monkeypatch) -> AsyncGenerator[DatabaseInfra, None]:
    """Provides an initialized DatabaseInfra with a fresh test database.

    Uses pgdbm's AsyncTestDatabase to create an isolated test database,
    then initializes DatabaseInfra against it.
    """
    test_config = DatabaseTestConfig.from_env()
    test_db = AsyncTestDatabase(test_config)
    db_name = await test_db.create_test_database()

    database_url = build_database_url(test_config, db_name)
    monkeypatch.setenv("DATABASE_URL", database_url)

    infra = DatabaseInfra()
    await infra.initialize()

    try:
        yield infra
    finally:
        await infra.close()
        await test_db.drop_test_database()


@pytest_asyncio.fixture
async def db_infra_uninitialized(monkeypatch) -> AsyncGenerator[DatabaseInfra, None]:
    """Provides an uninitialized DatabaseInfra with a test database ready.

    Use this fixture to test initialization behavior, including race conditions.
    The caller is responsible for calling initialize().
    """
    test_config = DatabaseTestConfig.from_env()
    test_db = AsyncTestDatabase(test_config)
    db_name = await test_db.create_test_database()

    database_url = build_database_url(test_config, db_name)
    monkeypatch.setenv("DATABASE_URL", database_url)

    infra = DatabaseInfra()

    try:
        yield infra
    finally:
        if infra.is_initialized:
            await infra.close()
        await test_db.drop_test_database()


@pytest_asyncio.fixture
async def aweb_db_infra(monkeypatch) -> AsyncGenerator[AwebDatabaseInfra, None]:
    """Provides an initialized aweb DatabaseInfra with a fresh test database."""

    test_config = DatabaseTestConfig.from_env()
    test_db = AsyncTestDatabase(test_config)
    db_name = await test_db.create_test_database()

    database_url = build_database_url(test_config, db_name)
    monkeypatch.setenv("DATABASE_URL", database_url)

    infra = AwebDatabaseInfra()
    await infra.initialize()

    try:
        yield infra
    finally:
        await infra.close()
        await test_db.drop_test_database()


def _wait_for_server(url: str, timeout: float = 10.0) -> bool:
    """Wait for server to become healthy."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(f"{url}/health", timeout=1.0)
            if resp.status_code == 200:
                return True
        except httpx.RequestError:
            pass
        time.sleep(0.1)
    return False


async def _create_test_database() -> tuple[AsyncTestDatabase, str, str]:
    """Create test database and return (test_db, db_name, url)."""
    test_config = DatabaseTestConfig.from_env()
    test_db = AsyncTestDatabase(test_config)
    db_name = await test_db.create_test_database()
    database_url = build_database_url(test_config, db_name)
    return test_db, db_name, database_url


async def _drop_test_database(db_name: str) -> None:
    """Drop test database using a fresh connection."""
    test_config = DatabaseTestConfig.from_env()
    test_db = AsyncTestDatabase(test_config)
    test_db._test_db_name = db_name  # Set the name to drop
    await test_db.drop_test_database()


def _kill_stale_server(port: int) -> None:
    """Kill any process listening on the test server port."""
    try:
        # Use lsof to find processes on the port
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    logger.warning(f"Killed stale process {pid} on port {port}")
                except (ProcessLookupError, ValueError):
                    pass
            time.sleep(0.5)  # Give OS time to release the port
    except FileNotFoundError:
        pass  # lsof not available (e.g., Windows)


@pytest.fixture(scope="session")
def beadhub_server():
    """Start a BeadHub server for integration tests.

    This fixture starts the server once per test session for efficiency.
    It creates a test database, starts the server subprocess, waits for
    it to be ready, and tears everything down after all tests complete.

    Yields:
        str: The server URL (http://localhost:18765)
    """
    # Clean up any stale server from previous runs
    _kill_stale_server(TEST_SERVER_PORT)

    # Create test database using asyncio.run (proper event loop management)
    test_db, db_name, database_url = asyncio.run(_create_test_database())

    # Check Redis availability and flush - ensure cleanup before any skip
    redis_client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        redis_client.ping()
        redis_client.flushdb()
    except Exception:
        redis_client.close()
        # Clean up database before skipping
        try:
            asyncio.run(_drop_test_database(db_name))
        except Exception as e:
            logger.warning(f"Failed to drop test database {db_name} during skip: {e}")
        pytest.skip("Redis is not available")
    finally:
        redis_client.close()

    # Start server with test configuration
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "REDIS_URL": TEST_REDIS_URL,
        "BEADHUB_HOST": "127.0.0.1",
        "BEADHUB_PORT": str(TEST_SERVER_PORT),
        "BEADHUB_LOG_JSON": "false",
        "BEADHUB_LOG_LEVEL": "warning",
        # Higher rate limit for integration tests (many init calls in session)
        "BEADHUB_INIT_RATE_LIMIT": "1000",
    }

    server_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "beadhub.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(TEST_SERVER_PORT),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        if not _wait_for_server(TEST_SERVER_URL, timeout=15.0):
            server_proc.terminate()
            try:
                stdout, stderr = server_proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()
                stdout, stderr = server_proc.communicate()
            pytest.fail(
                f"BeadHub server failed to start.\n"
                f"stdout: {stdout.decode()}\n"
                f"stderr: {stderr.decode()}"
            )

        yield TEST_SERVER_URL
    finally:
        # Stop server
        server_proc.send_signal(signal.SIGTERM)
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.wait()

        # Flush Redis (clean up server state before dropping database)
        redis_client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
        try:
            redis_client.flushdb()
        except Exception as e:
            logger.warning(f"Failed to flush Redis during cleanup: {e}")
        finally:
            redis_client.close()

        # Cleanup database using asyncio.run (proper event loop management)
        try:
            asyncio.run(_drop_test_database(db_name))
        except Exception as e:
            logger.warning(f"Failed to drop test database {db_name}: {e}")

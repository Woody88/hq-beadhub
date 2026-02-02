"""Test DatabaseInfra class."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_initialize_concurrent_calls_single_pool(db_infra_uninitialized):
    """Concurrent calls to initialize() should only create one pool.

    Without proper locking, concurrent initialize() calls could both pass
    the `if self._initialized` check and create duplicate pools.
    """
    db_infra = db_infra_uninitialized

    # Call initialize() concurrently 5 times
    tasks = [db_infra.initialize() for _ in range(5)]
    await asyncio.gather(*tasks)

    # Should be initialized with a single pool
    assert db_infra._initialized is True
    assert db_infra._shared_pool is not None

    # Managers should work correctly
    server_manager = db_infra.get_manager("server")
    beads_manager = db_infra.get_manager("beads")
    assert server_manager is not None
    assert beads_manager is not None

    # Verify we can actually query (proves the pool is valid)
    result = await server_manager.fetch_value("SELECT 1")
    assert result == 1


@pytest.mark.asyncio
async def test_initialize_idempotent(db_infra_uninitialized):
    """Subsequent calls to initialize() should be no-ops."""
    db_infra = db_infra_uninitialized

    # First call initializes
    await db_infra.initialize()
    first_pool = db_infra._shared_pool
    assert db_infra._initialized is True

    # Second call should be no-op, same pool
    await db_infra.initialize()
    assert db_infra._shared_pool is first_pool

    # Third call should also be no-op
    await db_infra.initialize()
    assert db_infra._shared_pool is first_pool


@pytest.mark.asyncio
async def test_db_infra_fixture_works(db_infra):
    """Basic test that the db_infra fixture provides a working instance."""
    assert db_infra._initialized is True

    server_manager = db_infra.get_manager("server")
    result = await server_manager.fetch_value("SELECT 1")
    assert result == 1

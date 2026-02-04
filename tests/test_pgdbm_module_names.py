from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_pgdbm_schema_migrations_module_names_are_stable(db_infra):
    """Guardrail: keep migration module_name stable across extraction.

    beadhub owns migrations for:
    - server schema via module_name 'beadhub-server'
    - beads schema via module_name 'beadhub-beads'

    beadhub embeds the aweb protocol and applies aweb migrations with:
    - aweb schema via module_name 'aweb-aweb'
    """

    server_db = db_infra.get_manager("server")
    beads_db = db_infra.get_manager("beads")
    aweb_db = db_infra.get_manager("aweb")

    server_names = {
        r["module_name"]
        for r in await server_db.fetch_all(
            "SELECT DISTINCT module_name FROM server.schema_migrations"
        )
        if r.get("module_name")
    }
    beads_names = {
        r["module_name"]
        for r in await beads_db.fetch_all(
            "SELECT DISTINCT module_name FROM beads.schema_migrations"
        )
        if r.get("module_name")
    }
    aweb_names = {
        r["module_name"]
        for r in await aweb_db.fetch_all("SELECT DISTINCT module_name FROM aweb.schema_migrations")
        if r.get("module_name")
    }

    assert "beadhub-server" in server_names
    assert "beadhub-beads" in beads_names
    assert "aweb-aweb" in aweb_names

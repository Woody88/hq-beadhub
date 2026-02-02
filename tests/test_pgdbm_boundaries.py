from __future__ import annotations

from pathlib import Path


def _read_sql_files(root: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*.sql")):
        files.append((path, path.read_text(encoding="utf-8")))
    return files


def test_beadhub_migrations_do_not_reference_aweb_schema() -> None:
    """Guardrail: keep beadhub schema extractable from aweb.

    The aweb schema lives in a separate repo after extraction; beadhub must not
    create SQL-level coupling to `aweb.*` objects.
    """

    repo_root = Path(__file__).resolve().parents[1]
    beadhub_migrations = repo_root / "src" / "beadhub" / "migrations"

    for path, content in _read_sql_files(beadhub_migrations):
        assert "aweb." not in content, f"{path} contains a cross-boundary aweb schema reference"

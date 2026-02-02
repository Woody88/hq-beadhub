"""Workspace configuration reading from .beadhub files."""

from dataclasses import dataclass
from pathlib import Path

MAX_CONFIG_SIZE = 4096  # 4KB max for .beadhub file


@dataclass
class WorkspaceConfig:
    """Configuration loaded from a .beadhub file."""

    workspace_id: str | None = None
    beadhub_url: str | None = None
    alias: str | None = None
    human_name: str | None = None
    project_slug: str | None = None
    repo_origin: str | None = None


def _strip_quotes(value: str) -> str:
    """Strip matching quotes from a value string.

    Only removes quotes if they match (both single or both double).
    """
    value = value.strip()
    if len(value) >= 2:
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            return value[1:-1]
    return value


def _parse_beadhub_file(content: str) -> dict[str, str]:
    """Parse simple YAML-like .beadhub config file.

    Format:
        # comments are ignored
        key: "value"   # quoted values
        key: value     # unquoted values

    Note: This is NOT a full YAML parser. It only supports simple key: value lines.
    """
    config: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if not key:
                continue
            value = _strip_quotes(value)
            if value:
                config[key] = value
    return config


def load_workspace_config(path: Path | None = None) -> WorkspaceConfig | None:
    """Load workspace configuration from .beadhub file.

    Args:
        path: Directory containing .beadhub file. Defaults to current directory.
              Security note: Caller must ensure this path is trusted.

    Returns:
        WorkspaceConfig if file exists, None if file doesn't exist.

    Raises:
        ValueError: If file is too large or unreadable.
    """
    if path is None:
        path = Path.cwd()

    config_file = path / ".beadhub"
    if not config_file.exists():
        return None

    try:
        file_size = config_file.stat().st_size
        if file_size > MAX_CONFIG_SIZE:
            raise ValueError(f".beadhub file too large ({file_size} bytes, max {MAX_CONFIG_SIZE})")
        content = config_file.read_text(encoding="utf-8")
    except PermissionError:
        raise ValueError(f"Cannot read {config_file}: Permission denied")
    except UnicodeDecodeError:
        raise ValueError(f"{config_file} is not valid UTF-8 text")
    except OSError as e:
        raise ValueError(f"Error reading {config_file}: {e}")

    parsed = _parse_beadhub_file(content)

    return WorkspaceConfig(
        workspace_id=parsed.get("workspace_id"),
        beadhub_url=parsed.get("beadhub_url"),
        alias=parsed.get("alias"),
        human_name=parsed.get("human_name"),
        project_slug=parsed.get("project_slug"),
        repo_origin=parsed.get("repo_origin"),
    )


def get_workspace_id(override: str | None = None, path: Path | None = None) -> str | None:
    """Get workspace_id, preferring explicit override over file.

    Args:
        override: Explicit workspace_id (takes precedence).
        path: Directory containing .beadhub file.

    Returns:
        workspace_id or None if not available.
    """
    if override:
        return override

    config = load_workspace_config(path)
    if config:
        return config.workspace_id

    return None


def get_project_slug(override: str | None = None, path: Path | None = None) -> str | None:
    """Get project_slug, preferring explicit override over file.

    Args:
        override: Explicit project_slug (takes precedence).
        path: Directory containing .beadhub file.

    Returns:
        project_slug or None if not available.
    """
    if override:
        return override

    config = load_workspace_config(path)
    if config:
        return config.project_slug

    return None


def get_human_name(override: str | None = None, path: Path | None = None) -> str | None:
    """Get human_name, preferring explicit override over file.

    Args:
        override: Explicit human_name (takes precedence).
        path: Directory containing .beadhub file.

    Returns:
        human_name or None if not available.
    """
    if override:
        return override

    config = load_workspace_config(path)
    if config:
        return config.human_name

    return None


def get_alias(override: str | None = None, path: Path | None = None) -> str | None:
    """Get alias, preferring explicit override over file.

    Args:
        override: Explicit alias (takes precedence).
        path: Directory containing .beadhub file.

    Returns:
        alias or None if not available.
    """
    if override:
        return override

    config = load_workspace_config(path)
    if config:
        return config.alias

    return None


def get_repo_origin(override: str | None = None, path: Path | None = None) -> str | None:
    """Get repo_origin, preferring explicit override over file.

    Args:
        override: Explicit repo_origin (takes precedence).
        path: Directory containing .beadhub file.

    Returns:
        repo_origin or None if not available.
    """
    if override:
        return override

    config = load_workspace_config(path)
    if config:
        return config.repo_origin

    return None

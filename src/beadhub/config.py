import os
from dataclasses import dataclass


@dataclass
class Settings:
    host: str
    port: int
    log_level: str
    reload: bool
    redis_url: str
    database_url: str
    presence_ttl_seconds: int
    dashboard_human: str


def get_settings() -> Settings:
    """
    Load settings from environment at call time.

    Accepts both prefixed (BEADHUB_*) and unprefixed env vars for flexibility.
    """
    database_url = os.getenv("BEADHUB_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError(
            "DATABASE_URL or BEADHUB_DATABASE_URL environment variable is required. "
            "Example: postgresql://user:pass@localhost:5432/beadhub"
        )

    redis_url = (
        os.getenv("BEADHUB_REDIS_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379/0"
    )

    port_str = os.getenv("BEADHUB_PORT", "8000")
    try:
        port = int(port_str)
        if not 1 <= port <= 65535:
            raise ValueError(f"BEADHUB_PORT must be between 1 and 65535, got {port}")
    except ValueError as e:
        if "invalid literal" in str(e):
            raise ValueError(f"BEADHUB_PORT must be a valid integer, got '{port_str}'")
        raise

    presence_ttl_str = os.getenv("BEADHUB_PRESENCE_TTL_SECONDS", "1800")
    try:
        presence_ttl = int(presence_ttl_str)
        if presence_ttl < 10:
            raise ValueError("BEADHUB_PRESENCE_TTL_SECONDS must be at least 10")
    except ValueError as e:
        if "invalid literal" in str(e):
            raise ValueError(
                f"BEADHUB_PRESENCE_TTL_SECONDS must be a valid integer, got '{presence_ttl_str}'"
            )
        raise

    return Settings(
        host=os.getenv("BEADHUB_HOST", "0.0.0.0"),
        port=port,
        log_level=os.getenv("BEADHUB_LOG_LEVEL", "info"),
        reload=os.getenv("BEADHUB_RELOAD", "false").lower() == "true",
        redis_url=redis_url,
        database_url=database_url,
        presence_ttl_seconds=presence_ttl,
        dashboard_human=os.getenv("BEADHUB_DASHBOARD_HUMAN", "admin"),
    )

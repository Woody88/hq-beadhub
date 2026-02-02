from .api import create_app
from .cli import app
from .db import DatabaseInfra

__all__ = ["create_app", "DatabaseInfra", "app", "main"]


def main() -> None:
    app()

from importlib.metadata import version

from .api import create_app
from .cli import app
from .db import DatabaseInfra

__version__ = version("beadhub")
__all__ = ["__version__", "create_app", "DatabaseInfra", "app", "main"]


def main() -> None:
    app()

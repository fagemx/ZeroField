"""Locate bundled SQL and browser assets in a checkout or an installed wheel."""
from pathlib import Path


def resource_path(*parts: str) -> Path:
    package = Path(__file__).resolve().parent
    checkout = package.parent
    source = checkout.joinpath(*parts)
    if (checkout / "pyproject.toml").is_file() and source.exists():
        return source
    return package.joinpath(*parts)

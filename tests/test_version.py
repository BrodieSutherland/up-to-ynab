import tomllib
from pathlib import Path

import app


def test_pyproject_version_matches_app_version():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        declared = tomllib.load(f)["project"]["version"]

    assert declared == app.VERSION == "3.1.0"

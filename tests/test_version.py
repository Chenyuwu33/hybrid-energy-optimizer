import tomllib
from pathlib import Path

import energy_hub


def test_package_and_project_versions_are_synchronized_for_v021() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert energy_hub.__version__ == "0.2.1"
    assert metadata["project"]["version"] == "0.2.1"

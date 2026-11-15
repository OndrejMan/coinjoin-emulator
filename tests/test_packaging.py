"""Distribution package-discovery contract."""

import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_setuptools_discovers_runtime_manager_subpackages() -> None:
    configuration = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    discovery = configuration["tool"]["setuptools"]["packages"]["find"]
    include = discovery["include"]
    required_packages = {
        "manager.commands",
        "manager.driver",
        "manager.engine",
        "manager.engine.base",
        "manager.engine.joinmarket",
        "manager.wasabi_clients",
        "manager.wasabi_clients.joinmarket_clients",
    }

    for package in required_packages:
        assert (PROJECT_ROOT / package.replace(".", "/")).is_dir()
        assert any(fnmatchcase(package, pattern) for pattern in include)

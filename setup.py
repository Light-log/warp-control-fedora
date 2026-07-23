import ast
import re
from pathlib import Path

from setuptools import __version__ as setuptools_version
from setuptools import find_packages, setup


PYPROJECT = (Path(__file__).parent / "pyproject.toml").read_text(encoding="utf-8")


def project_string(key: str) -> str:
    match = re.search(rf'^{re.escape(key)} = "([^"]+)"$', PYPROJECT, re.MULTILINE)
    if match is None:
        raise RuntimeError(f"missing {key} in pyproject.toml")
    return match.group(1)


def project_dependencies() -> list[str]:
    match = re.search(
        r"^dependencies\s*=\s*(\[.*?\])",
        PYPROJECT,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise RuntimeError("missing dependencies in pyproject.toml")
    dependencies = ast.literal_eval(match.group(1))
    if not isinstance(dependencies, list) or not all(
        isinstance(dependency, str) for dependency in dependencies
    ):
        raise RuntimeError("dependencies must be a list of strings")
    return dependencies


def legacy_metadata() -> dict[str, object]:
    major = int(setuptools_version.split(".", 1)[0])
    if major >= 61:
        return {}
    return {
        "name": project_string("name"),
        "version": project_string("version"),
        "description": project_string("description"),
        "python_requires": project_string("requires-python"),
        "install_requires": project_dependencies(),
        "package_dir": {"": "src"},
        "packages": find_packages("src"),
        "package_data": {"warp_control.assets": ["*.svg"]},
        "entry_points": {
            "console_scripts": ["warp-control=warp_control.__main__:main"]
        },
    }


setup(**legacy_metadata())

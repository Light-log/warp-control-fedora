from pathlib import Path


def test_runtime_dependencies_include_el9_compatible_idna():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert 'dependencies = ["idna>=2.10"]' in pyproject

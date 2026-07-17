from pathlib import Path


def test_runtime_dependencies_include_modern_idna():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert 'dependencies = ["idna>=3.6"]' in pyproject

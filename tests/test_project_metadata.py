import configparser
from pathlib import Path


def test_runtime_dependencies_include_modern_idna():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert 'dependencies = ["idna>=3.6"]' in pyproject


def test_desktop_entry_has_exact_required_metadata():
    desktop_path = Path(__file__).parents[1] / "data" / "com.robler.warpcontrol.desktop"
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(desktop_path.read_text(encoding="utf-8"))

    assert parser.sections() == ["Desktop Entry"]
    assert dict(parser["Desktop Entry"]) == {
        "Type": "Application",
        "Name": "WARP Control",
        "Exec": "/usr/bin/warp-control",
        "Icon": "com.robler.warpcontrol",
        "Categories": "Network;Utility;",
        "StartupNotify": "false",
    }

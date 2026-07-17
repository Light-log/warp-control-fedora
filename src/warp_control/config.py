import json
import os
import re
import tempfile
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


SCHEMA_VERSION = 2
DEFAULT_COLORS = {
    "connected": {"primary": "#16A34A", "secondary": "#4ADE80"},
    "connecting": {"primary": "#F38020", "secondary": "#FCAD32"},
    "disconnected": {"primary": "#64748B", "secondary": "#94A3B8"},
    "error": {"primary": "#DC2626", "secondary": "#F87171"},
}
_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class UnsupportedConfigVersionError(ValueError):
    """Raised when a config was written by a newer schema."""


def _default_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "warp-control" / "config.json"


def _valid_color(value: object, default: str) -> str:
    if isinstance(value, str) and _COLOR_PATTERN.fullmatch(value):
        return value
    return default


def _load_colors(value: object) -> Dict[str, Dict[str, str]]:
    colors = deepcopy(DEFAULT_COLORS)
    if not isinstance(value, dict):
        return colors

    for state, defaults in DEFAULT_COLORS.items():
        candidate = value.get(state)
        if not isinstance(candidate, dict):
            continue
        for role, default in defaults.items():
            colors[state][role] = _valid_color(candidate.get(role), default)
    return colors


def _normalized_values(raw: object) -> Dict[str, object]:
    if not isinstance(raw, dict):
        raw = {}

    theme = raw.get("theme")
    autostart_enabled = raw.get("autostart_enabled")
    auto_update_enabled = raw.get("auto_update_enabled")
    update_interval_seconds = raw.get("update_interval_seconds")
    return {
        "schema_version": SCHEMA_VERSION,
        "theme": theme if theme in {"light", "dark"} else "dark",
        "accent": _valid_color(raw.get("accent"), "#F38020"),
        "colors": _load_colors(raw.get("colors")),
        "autostart_enabled": (
            autostart_enabled
            if isinstance(autostart_enabled, bool)
            else True
        ),
        "auto_update_enabled": (
            auto_update_enabled
            if isinstance(auto_update_enabled, bool)
            else True
        ),
        "update_interval_seconds": (
            update_interval_seconds
            if isinstance(update_interval_seconds, int)
            and not isinstance(update_interval_seconds, bool)
            and update_interval_seconds > 0
            else 5
        ),
    }


@dataclass
class Config:
    schema_version: int = SCHEMA_VERSION
    theme: str = "dark"
    accent: str = "#F38020"
    colors: Dict[str, Dict[str, str]] = field(
        default_factory=lambda: deepcopy(DEFAULT_COLORS)
    )
    autostart_enabled: bool = True
    auto_update_enabled: bool = True
    update_interval_seconds: int = 5
    path: Path = field(default_factory=_default_path, repr=False, compare=False)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        config_path = Path(path) if path is not None else _default_path()
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}

        if isinstance(raw, dict):
            schema_version = raw.get("schema_version")
            if (
                isinstance(schema_version, int)
                and not isinstance(schema_version, bool)
                and schema_version > SCHEMA_VERSION
            ):
                raise UnsupportedConfigVersionError(
                    f"Config schema {schema_version} is newer than supported "
                    f"schema {SCHEMA_VERSION}"
                )

        return cls(**_normalized_values(raw), path=config_path)

    def _normalize(self) -> Dict[str, object]:
        values = _normalized_values(
            {
                "schema_version": self.schema_version,
                "theme": self.theme,
                "accent": self.accent,
                "colors": self.colors,
                "autostart_enabled": self.autostart_enabled,
                "auto_update_enabled": self.auto_update_enabled,
                "update_interval_seconds": self.update_interval_seconds,
            }
        )
        for name, value in values.items():
            setattr(self, name, value)
        return values

    def save(self) -> None:
        data = self._normalize()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(data, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def reset(self) -> None:
        defaults = type(self)(path=self.path)
        self.schema_version = defaults.schema_version
        self.theme = defaults.theme
        self.accent = defaults.accent
        self.colors = defaults.colors
        self.autostart_enabled = defaults.autostart_enabled
        self.auto_update_enabled = defaults.auto_update_enabled
        self.update_interval_seconds = defaults.update_interval_seconds
        self.save()

"""Resolve packaged runtime images without assuming a source checkout."""

from importlib import resources
from pathlib import Path
from typing import Optional, Union


def runtime_asset_path(
    name: str, directory: Optional[Union[Path, str]] = None
) -> Path:
    if directory is not None:
        return Path(directory) / name
    resource = resources.files("warp_control.assets").joinpath(name)
    return Path(str(resource))

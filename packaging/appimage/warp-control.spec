# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir recipe for the portable GTK application."""

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks.gi import GiModuleInfo


appimage_dir = Path(SPECPATH)
repository = appimage_dir.parents[1]
source_root = repository / "src"
sys.path.insert(0, str(source_root))
warp_control_datas = collect_data_files("warp_control")

# Importing the GI namespaces explicitly lets PyInstaller's GI hooks collect
# their typelibs, shared-library dependencies, schemas, loaders and data.
hidden_imports = [
    "gi._gi",
    "gi.repository.GLib",
    "gi.repository.GObject",
    "gi.repository.Gio",
    "gi.repository.Gdk",
    "gi.repository.GdkPixbuf",
    "gi.repository.Gtk",
    "gi.repository.Pango",
    "gi.repository.cairo",
    "gi.repository.AyatanaAppIndicator3",
]

gi_namespaces = [
    ("GLib", "2.0"),
    ("GObject", "2.0"),
    ("Gio", "2.0"),
    ("GdkPixbuf", "2.0"),
    ("Pango", "1.0"),
    ("cairo", "1.0"),
    ("Gdk", "3.0"),
    ("Gtk", "3.0"),
    ("AyatanaAppIndicator3", "0.1"),
]
gi_binaries = []
gi_datas = []
for namespace, api_version in gi_namespaces:
    namespace_binaries, namespace_datas, namespace_imports = GiModuleInfo(
        namespace, api_version
    ).collect_typelib_data()
    gi_binaries += namespace_binaries
    gi_datas += namespace_datas
    hidden_imports += namespace_imports

analysis = Analysis(
    [str(appimage_dir / "entrypoint.py")],
    pathex=[str(source_root)],
    binaries=gi_binaries,
    datas=warp_control_datas + gi_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="warp-control",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="warp-control",
)

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPECPATH).parent
GENERATED = ROOT / "build" / "generated"

a = Analysis(
    [str(ROOT / "app" / "desktop_app.py")],
    pathex=[str(ROOT / "src"), str(GENERATED)],
    binaries=[],
    datas=[],
    hiddenimports=["pypdf", "raggg_build_edition"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WavEDA_Assistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(ROOT / "build" / "waveda.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WavEDA_Assistant",
)

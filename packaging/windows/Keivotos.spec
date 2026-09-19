# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules, copy_metadata


ROOT = Path(SPECPATH).parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from delivery import delivery_plan

PLAN = delivery_plan('win32')
MODULE_METADATA = [entry for package in PLAN.metadata_packages for entry in copy_metadata(package, recursive=True)]
MODULE_IMPORTS = [name for package in PLAN.collect_packages for name in collect_submodules(package)]
UVICORN_HIDDEN_IMPORTS = [
    *collect_submodules("uvicorn.lifespan"),
    *collect_submodules("uvicorn.loops"),
    *collect_submodules("uvicorn.protocols.http"),
    *collect_submodules("uvicorn.protocols.websockets"),
]

analysis = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT), str(ROOT / "backend")],
    binaries=[],
    datas=MODULE_METADATA + [
        (str(ROOT / "frontend" / "dist"), "frontend/dist"),
        *((str(ROOT / path), str(Path(path).parent)) for _label, path in PLAN.helpers),
        (str(ROOT / "config.json"), "."),
    ],
    hiddenimports=[*PLAN.hidden_imports, *MODULE_IMPORTS, *UVICORN_HIDDEN_IMPORTS],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["gallery_dl", "imageio_ffmpeg"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Keivotos",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=str(ROOT / "packaging" / "windows" / "assets" / "keivotos.ico"),
    version=str(ROOT / "packaging" / "windows" / "version_info.txt"),
)
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Keivotos",
)

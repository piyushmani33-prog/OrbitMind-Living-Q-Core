# OrbitMind U5.0B1 internal one-folder packaging spike. This spec is source only
# until a separate frozen-build approval explicitly authorizes execution.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
SOURCE = ROOT / "src"
MIGRATIONS = ROOT / "migrations"
SAMPLES = ROOT / "data" / "samples"
LAUNCHER = SOURCE / "orbitmind" / "runtime" / "launcher.py"

if not LAUNCHER.is_file():
    raise FileNotFoundError(
        "Required packaging source is missing: src/orbitmind/runtime/launcher.py"
    )

datas = [
    (str(ROOT / "alembic.ini"), "."),
    (str(MIGRATIONS / "env.py"), "migrations"),
    (str(MIGRATIONS / "script.py.mako"), "migrations"),
    *[(str(path), "migrations/versions") for path in sorted((MIGRATIONS / "versions").glob("*.py"))],
    (
        str(SOURCE / "orbitmind" / "api" / "assets" / "trajectory_replay.js"),
        "orbitmind/api/assets",
    ),
    (str(SAMPLES / "catalog.json"), "data/samples"),
    (str(SAMPLES / "iss_zarya.tle"), "data/samples"),
]
datas += collect_data_files("matplotlib")
for distribution in ("fastapi", "SQLAlchemy", "sgp4", "numpy", "matplotlib"):
    datas += copy_metadata(distribution)

hiddenimports = [
    "matplotlib.backends.backend_agg",
    "orbitmind.persistence.research_models",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "uvicorn.lifespan.on",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
]

a = Analysis(
    [str(LAUNCHER)],
    pathex=[str(SOURCE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["psycopg", "psycopg_binary", "qiskit", "qiskit_aer", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OrbitMind",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OrbitMind",
)

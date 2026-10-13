# PyInstaller spec: onedir bundle with a windowed GUI and a console CLI sharing one runtime.
# Build with: python packaging/build.py   (do not call pyinstaller directly; build.py adds provenance files)
# onedir (not onefile) keeps Qt and libsndfile as replaceable shared libraries (LGPL compliance, spec 15 section 5).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
datas = collect_data_files("sonicclue", includes=["procedures/definitions/*.json"])
binaries = collect_dynamic_libs("sounddevice") + collect_dynamic_libs("soundfile")
# Report figures use matplotlib's Agg backend only; GUI backends, GTK (pulled via system PyGObject on some
# build hosts), pandas and lxml are not used by SonicClue.
excludes = ["tkinter", "PyQt5", "PyQt6", "IPython", "pytest", "hypothesis", "jsonschema", "gi", "pandas", "lxml",
            "matplotlib.backends.backend_gtk3agg", "matplotlib.backends.backend_gtk4agg", "matplotlib.backends.backend_tkagg",
            "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_qt", "matplotlib.backends.backend_wx"]
hidden = ["sonicclue.gui.screens_case", "sonicclue.gui.screens_setup", "sonicclue.gui.screens_measure", "sonicclue.gui.screens_dx",
          "matplotlib.backends.backend_agg", "_cffi_backend"]

a_gui = Analysis([str(ROOT / "packaging/entry_gui.py")], pathex=[str(ROOT / "src")], binaries=binaries, datas=datas,  # noqa: F821
                 hiddenimports=hidden, excludes=excludes, noarchive=False)
a_cli = Analysis([str(ROOT / "packaging/entry_cli.py")], pathex=[str(ROOT / "src")], binaries=binaries, datas=datas,  # noqa: F821
                 hiddenimports=hidden, excludes=excludes, noarchive=False)

pyz_gui = PYZ(a_gui.pure)  # noqa: F821
pyz_cli = PYZ(a_cli.pure)  # noqa: F821
exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="SonicClue", console=False,  # noqa: F821
              debug=False, strip=False, upx=False)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="sonicclue-cli", console=True,  # noqa: F821
              debug=False, strip=False, upx=False)
coll = COLLECT(exe_gui, a_gui.binaries, a_gui.datas, exe_cli, a_cli.binaries, a_cli.datas,  # noqa: F821
               strip=False, upx=False, name="SonicClue")

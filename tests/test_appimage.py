"""AppImage launch routing works after moving the staged directory."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="Linux AppImage launcher")
def test_appdir_routes_gui_and_cli_after_relocation(tmp_path):
    script = Path(__file__).resolve().parents[1] / "packaging/build_appimage.py"
    spec = importlib.util.spec_from_file_location("build_appimage", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for executable in ("SonicClue", "sonicclue-cli"):
        p = bundle / executable
        p.write_text('#!/bin/sh\nprintf "%s\\n" "' + executable + '" "$@"\n')
        p.chmod(0o755)
    (bundle / "BUILD_INFO.json").write_text('{"version":"0.1.0"}')
    appdir = tmp_path / "AppDir"
    module.stage_appdir(bundle, appdir)
    moved = tmp_path / "directory with spaces"
    shutil.move(appdir, moved)
    for args, expected in [(["hello world"], ["SonicClue", "hello world"]),
                           (["--cli", "--version"], ["sonicclue-cli", "--version"])]:
        result = subprocess.run([str(moved / "AppRun"), *args], check=True, capture_output=True, text=True)
        assert result.stdout.splitlines() == expected
    assert (moved / "usr/lib/sonicclue/BUILD_INFO.json").read_text() == '{"version":"0.1.0"}'

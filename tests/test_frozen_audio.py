"""Frozen audio discovers bundled PortAudio without host linker-cache entries."""

import ctypes.util
import os
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="frozen Linux audio and graphics")

HOOK = Path(__file__).resolve().parent.parent / "packaging/pyi_rth_portaudio.py"


@pytest.mark.parametrize("frozen,library_present", [(True, True), (True, False), (False, True)])
def test_bundled_portaudio_lookup_preserves_system_fallback(monkeypatch, tmp_path, frozen, library_present):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    library = tmp_path / "libportaudio.so.2"
    if library_present:
        library.write_bytes(b"native-library-fixture")

    def system_find(name):
        return {"portaudio": None, "other": "libother.so.1"}.get(name)

    monkeypatch.setattr(ctypes.util, "find_library", system_find)
    runpy.run_path(str(HOOK))
    assert ctypes.util.find_library("portaudio") == (str(library) if frozen and library_present else None)
    assert ctypes.util.find_library("other") == "libother.so.1"
    assert ctypes.util.find_library("nonexistent") is None


@pytest.mark.parametrize("native_available", [True, False])
def test_linux_bundle_collects_graphics_dispatchers_or_reports_prerequisite(monkeypatch, native_available):
    import PyInstaller.depend.bindepend as bindepend
    import PyInstaller.utils.hooks as hooks

    monkeypatch.setattr(sys, "platform", "linux")
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: True if str(path) == "/usr/share/alsa/alsa.conf" else original_is_file(path))
    monkeypatch.setattr(ctypes.util, "find_library", lambda name: f"lib{name}.so.1")
    monkeypatch.setattr(bindepend, "resolve_library_path",
                        lambda name: f"/native/{name}" if native_available else None)
    monkeypatch.setattr(hooks, "collect_data_files", lambda *args, **kwargs: [])
    monkeypatch.setattr(hooks, "collect_dynamic_libs", lambda *args, **kwargs: [])
    analyses = []

    def analysis(*args, **kwargs):
        analyses.append(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    globals_ = {"SPECPATH": str(HOOK.parent), "Analysis": analysis,
                "PYZ": lambda *args, **kwargs: None, "EXE": lambda *args, **kwargs: None,
                "COLLECT": lambda *args, **kwargs: None}
    if not native_available:
        with pytest.raises(RuntimeError, match="GL"):
            runpy.run_path(str(HOOK.parent / "sonicclue.spec"), init_globals=globals_)
        return
    runpy.run_path(str(HOOK.parent / "sonicclue.spec"), init_globals=globals_)
    for kwargs in analyses:
        assert ("/native/libGL.so.1", ".") in kwargs["binaries"]
        assert ("/native/libEGL.so.1", ".") in kwargs["binaries"]
        assert ("/native/libGLX.so.1", ".") in kwargs["binaries"]
        assert ("/native/libGLdispatch.so.1", ".") in kwargs["binaries"]
        assert ("/native/libxcb.so.1", ".") in kwargs["binaries"]
        assert str(HOOK) in kwargs["runtime_hooks"]
        assert ("/usr/share/alsa", "alsa") in kwargs["datas"]


@pytest.mark.parametrize("host_present,explicit", [(False, {}), (True, {}),
    (False, {"ALSA_CONFIG_PATH": "/custom/alsa.conf"}), (False, {"ALSA_CONFIG_DIR": "/custom/alsa"})])
def test_alsa_data_fallback_preserves_host_and_explicit_configuration(monkeypatch, tmp_path, host_present, explicit):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    for name in ("ALSA_CONFIG_PATH", "ALSA_CONFIG_DIR"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name, raising=False)
    for name, value in explicit.items():
        monkeypatch.setenv(name, value)
    alsa = tmp_path / "alsa"
    alsa.mkdir()
    (alsa / "alsa.conf").write_text("# bundled base configuration")
    original_is_file = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: host_present if str(path) == "/usr/share/alsa/alsa.conf" else original_is_file(path))
    runpy.run_path(str(HOOK))
    if not host_present and not explicit:
        assert os.environ["ALSA_CONFIG_PATH"] == str(alsa / "alsa.conf")
        assert os.environ["ALSA_CONFIG_DIR"] == str(alsa)
    else:
        for name in ("ALSA_CONFIG_PATH", "ALSA_CONFIG_DIR"):
            assert os.environ.get(name) == explicit.get(name)

"""Contracts are current and examples validate; architecture dependency rules hold."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "sonicclue"


def test_schemas_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "tools/gen_schemas.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_examples_behave_as_declared():
    r = subprocess.run([sys.executable, str(ROOT / "docs/specs/contracts/validate_examples.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_test_vectors_reproduce():
    r = subprocess.run([sys.executable, str(ROOT / "tools/gen_test_vectors.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------- architecture

FORBIDDEN = {
    "domain": {"dsp", "acquisition", "sensors", "sync", "compare", "diagnostics", "procedures", "stimulus", "storage", "reporting", "app",
               "cli", "gui", "analysis", "qualification"},
    "dsp": {"acquisition", "sensors", "sync", "compare", "diagnostics", "procedures", "stimulus", "storage", "reporting", "app", "cli",
            "gui", "analysis", "qualification"},
    "sensors": {"acquisition", "storage", "app", "cli", "gui", "diagnostics", "reporting", "compare"},
    "sync": {"acquisition", "storage", "app", "cli", "gui", "diagnostics", "reporting"},
    "analysis": {"acquisition", "storage", "app", "cli", "gui", "diagnostics", "reporting"},
    "compare": {"acquisition", "storage", "app", "cli", "gui", "diagnostics", "reporting"},
    "diagnostics": {"acquisition", "storage", "app", "cli", "gui", "reporting", "stimulus"},
    "procedures": {"acquisition", "storage", "app", "cli", "gui", "diagnostics", "reporting"},
    "acquisition": {"storage", "app", "cli", "gui", "diagnostics", "reporting", "compare"},
    "storage": {"acquisition", "app", "cli", "gui", "diagnostics", "reporting", "compare", "analysis"},
    "reporting": {"acquisition", "storage", "app", "cli", "gui"},
    "stimulus": {"storage", "app", "cli", "gui", "diagnostics", "reporting"},
    "qualification": {"app", "cli", "gui", "diagnostics", "reporting"},
    "app": {"cli", "gui"},
    "cli": {"gui"},
}
GUI_LIBS = {"PySide6", "pyqtgraph"}


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    pkg = path.relative_to(SRC).parts
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(pkg[:-1])[: len(pkg) - node.level] if node.level > 1 else list(pkg[:-1])
                if path.name == "__init__.py" and node.level == 1:
                    base = list(pkg[:-1])
                yield "sonicclue." + ".".join(base + ([node.module] if node.module else []))
            else:
                yield node.module or ""


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=lambda p: str(p.relative_to(SRC)))
def test_dependency_direction(path):
    parts = path.relative_to(SRC).parts
    top = parts[0] if len(parts) > 1 else None
    for imp in _imports(path):
        root = imp.split(".")[0]
        if root in GUI_LIBS:
            assert top == "gui", f"{path.relative_to(SRC)} imports {imp}: only gui may import Qt"
        if root == "sounddevice":
            assert top in ("acquisition", "app"), f"{path} imports sounddevice"
        if imp.startswith("sonicclue.") and top in FORBIDDEN:
            target = imp.split(".")[1] if len(imp.split(".")) > 1 else ""
            assert target not in FORBIDDEN[top], f"{path.relative_to(SRC)} ({top}) must not import sonicclue.{target}"


def test_reusable_dsp_has_no_heavy_imports():
    """dsp + domain must import without Qt, sounddevice, soundfile or the database."""
    code = ("import sys; import sonicclue.dsp.spectral, sonicclue.dsp.cross, sonicclue.dsp.tonal, sonicclue.dsp.transient, "
            "sonicclue.dsp.stats, sonicclue.dsp.signals, sonicclue.domain.model; "
            "bad=[m for m in ('PySide6','sounddevice','soundfile','sqlite3','pyqtgraph','matplotlib') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


_ = json

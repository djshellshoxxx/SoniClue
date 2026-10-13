#!/usr/bin/env python3
"""Build a standalone SonicClue bundle for the current OS (spec 19).

    python packaging/build.py [--skip-smoke]

Steps: write the build id → PyInstaller onedir → add docs, notices, SBOM, BUILD_INFO →
smoke test in a clean environment (CLI version, selftest, simulated demo; GUI
offscreen smoke) → zip (Windows) or tar.gz (Linux) → SHA256SUMS.txt.
Output: dist/SonicClue-<version>-<os>-x64/ and dist/SonicClue-<version>-<os>-x64.{zip|tar.gz}
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def sh(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    from sonicclue import __version__

    osname = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}[platform.system()]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "nogit"
    except OSError:
        sha = "nogit"
    build_id = f"{sha}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    bfile = ROOT / "src/sonicclue/_build.py"
    bfile.write_text(f'BUILD_ID = "{build_id}"\n')
    name = f"SonicClue-{__version__}-{osname}-x64"
    dist = ROOT / "dist"
    try:
        sh([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(dist), "--workpath", str(ROOT / "build"),
            str(ROOT / "packaging/sonicclue.spec")])
    finally:
        bfile.unlink(missing_ok=True)
    out = dist / name
    if out.exists():
        shutil.rmtree(out)
    (dist / "SonicClue").rename(out)
    for f in ("README.md", "LICENSE-NOTICE.md", "docs/USER_GUIDE.md", "docs/RELEASE_NOTES.md"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, out / Path(f).name)
    sh([sys.executable, str(ROOT / "tools/gen_notices.py"), str(out)])
    lock = ROOT / "requirements.lock"
    info = {"product": "SonicClue", "version": __version__, "build_id": build_id, "git": sha, "os": platform.platform(),
            "python": platform.python_version(), "lock_sha256": sha256(lock) if lock.exists() else None,
            "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "BUILD_INFO.json").write_text(json.dumps(info, indent=1))
    exe = ".exe" if osname == "windows" else ""
    cli, gui = out / f"sonicclue-cli{exe}", out / f"SonicClue{exe}"
    if "--skip-smoke" not in sys.argv:
        with tempfile.TemporaryDirectory() as td:
            env = {"PATH": os.environ.get("PATH", "") if osname == "windows" else "/usr/bin:/bin", "HOME": td, "USERPROFILE": td,
                   "SONICCLUE_WORKSPACE": str(Path(td) / "ws"), "QT_QPA_PLATFORM": "offscreen", "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                   "TEMP": td, "TMP": td}
            sh([str(cli), "--version"], env=env)
            sh([str(cli), "selftest"], env=env)
            sh([str(cli), "--sim-speed", "60", "demo", "--scale", "0.3"], env=env)
            sh([str(cli), "devices", "--backend", "simulated"], env=env)
            sh([str(gui), "--smoke-test", "--workspace", str(Path(td) / "ws")], env=env)
    if osname == "windows":
        arc = dist / f"{name}.zip"
        with zipfile.ZipFile(arc, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob("*")):
                z.write(p, Path(name) / p.relative_to(out))
    else:
        arc = dist / f"{name}.tar.gz"
        with tarfile.open(arc, "w:gz") as t:
            t.add(out, arcname=name)
    (dist / "SHA256SUMS.txt").write_text(f"{sha256(arc)}  {arc.name}\n")
    print(f"built {arc} ({arc.stat().st_size / 1e6:.1f} MB)\n{(dist / 'SHA256SUMS.txt').read_text()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

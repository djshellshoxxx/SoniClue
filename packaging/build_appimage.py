#!/usr/bin/env python3
"""Wrap a verified Linux standalone bundle as an unsigned AppImage.

python packaging/build_appimage.py --bundle dist/SonicClue-0.1.0-linux-x64 \
    --tool /path/to/appimagetool-x86_64.AppImage --out dist/SonicClue-0.1.0-x86_64.AppImage

Run with APPIMAGE_EXTRACT_AND_RUN=1 on systems without FUSE.
Pass --cli before CLI arguments; all other arguments launch the desktop app.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def stage_appdir(bundle: Path, appdir: Path) -> None:
    from PIL import Image, ImageDraw

    for name in ("SonicClue", "sonicclue-cli", "BUILD_INFO.json"):
        if not (bundle / name).is_file():
            raise FileNotFoundError(f"verified bundle is missing {name}")
    shutil.copytree(bundle, appdir / "usr/lib/sonicclue")
    launcher = appdir / "AppRun"
    launcher.write_text('''#!/bin/sh
set -eu
appdir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "${1:-}" = "--cli" ]; then
    shift
    exec "$appdir/usr/lib/sonicclue/sonicclue-cli" "$@"
fi
exec "$appdir/usr/lib/sonicclue/SonicClue" "$@"
''')
    launcher.chmod(0o755)
    (appdir / "sonicclue.desktop").write_text('''[Desktop Entry]
Type=Application
Name=SonicClue
Exec=AppRun
Icon=sonicclue
Categories=AudioVideo;Audio;
Terminal=false
''')
    icon = Image.new("RGB", (128, 128), "#17252a")
    ImageDraw.Draw(icon).line([(16, 64), (32, 64), (40, 36), (56, 92), (72, 36),
                              (88, 92), (96, 64), (112, 64)], fill="#81d6bd", width=6)
    icon.save(appdir / "sonicclue.png")
    shutil.copyfile(appdir / "sonicclue.png", appdir / ".DirIcon")
    # Uploaded/source files may be owner-only; staged squashfs files must be
    # readable after installation by another user. Never change the source.
    for path in [appdir, *appdir.rglob("*")]:
        path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--tool", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sonicclue-appimage-") as td:
        appdir = Path(td) / "SonicClue.AppDir"
        stage_appdir(args.bundle.resolve(), appdir)
        env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
        subprocess.run([str(args.tool.resolve()), str(appdir), str(args.out.resolve())], env=env, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

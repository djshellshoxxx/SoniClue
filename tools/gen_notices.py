#!/usr/bin/env python3
"""Generate THIRD_PARTY_NOTICES.md and SBOM.json from the installed (frozen) environment.

    python tools/gen_notices.py OUT_DIR
"""

from __future__ import annotations

import json
import sys
from importlib import metadata as md
from pathlib import Path

RUNTIME = ["numpy", "scipy", "pydantic", "pydantic-core", "annotated-types", "typing-extensions", "typing-inspection", "soundfile",
           "sounddevice", "cffi", "pycparser", "matplotlib", "contourpy", "cycler", "fonttools", "kiwisolver", "packaging", "pillow",
           "pyparsing", "python-dateutil", "six", "reportlab", "charset-normalizer", "PySide6", "PySide6-Essentials", "shiboken6",
           "pyqtgraph"]
EXTRA = [
    ("PortAudio", "bundled in sounddevice", "MIT-style (PortAudio licence)", "http://www.portaudio.com"),
    ("libsndfile", "bundled in soundfile", "LGPL-2.1-or-later (dynamically linked, replaceable)", "https://github.com/libsndfile/libsndfile"),
    ("Qt", "6.x bundled in PySide6", "LGPL-3.0 (dynamically linked, replaceable)", "https://download.qt.io/official_releases/qt/"),
    ("CPython", sys.version.split()[0], "PSF-2.0", "https://www.python.org"),
]


def lic(d) -> str:
    m = d.metadata
    s = m.get("License-Expression") or ""
    if not s:
        cls = [c.split("::")[-1].strip() for c in (m.get_all("Classifier") or []) if c.startswith("License")]
        s = "; ".join(cls) or (m.get("License") or "see package")[:80]
    return s


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    comps, lines = [], ["# Third-party notices", "", "SonicClue bundles the following components. Licence texts are included below where the",
                        "package ships them. LGPL components are dynamically linked shared libraries that can be replaced; corresponding",
                        "source code is available from the upstream URLs listed (written offer: contact Circuit Drift Labs for a copy).", ""]
    lines += ["| Component | Version | Licence | Source |", "|---|---|---|---|"]
    texts = []
    for name in RUNTIME:
        try:
            d = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        url = d.metadata.get("Home-page") or next((u.split(",", 1)[1].strip() for u in (d.metadata.get_all("Project-URL") or [])), "")
        comps.append({"type": "library", "name": name, "version": d.version, "licenses": [lic(d)], "purl": f"pkg:pypi/{name.lower()}@{d.version}"})
        lines.append(f"| {name} | {d.version} | {lic(d)} | {url} |")
        for f in d.files or []:
            fn = str(f).lower()
            if ("license" in fn or "copying" in fn or "notice" in fn) and fn.count("/") <= 2 and not fn.endswith((".py", ".pyc")):
                try:
                    texts.append((name, str(f), Path(d.locate_file(f)).read_text(errors="replace")[:20000]))
                except OSError:
                    pass
    for n, v, licence, url in EXTRA:
        comps.append({"type": "library", "name": n, "version": v, "licenses": [licence]})
        lines.append(f"| {n} | {v} | {licence} | {url} |")
    lines += ["", "## Licence texts", ""]
    for n, f, t in texts:
        lines += [f"### {n}: {f}", "", "```", t.strip(), "```", ""]
    (out / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines))
    (out / "SBOM.json").write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": comps}, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))

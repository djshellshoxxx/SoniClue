#!/usr/bin/env python3
"""Reference test vectors (docs/specs/test-vectors/vectors.json).

Each vector gives a deterministic input (generator, parameters, seed), the
expected value from an independent reference (closed form or extended
precision), the floating-point tolerance and, separately, the physical
measurement uncertainty where it applies. ``--check`` recomputes the values
with the installed SonicClue and fails if any is outside tolerance. Use it to
verify a build on a new machine.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs/specs/test-vectors/vectors.json"

from sonicclue.dsp import cross, signals, spectral, tonal  # noqa: E402

FS = 48000.0


def compute() -> list[dict]:
    v = []
    # TV-001 sine power via PSD main-lobe integration, Hann, off-bin
    x = signals.sine(1001.3, 0.3, 10.0, FS)
    plan = spectral.plan_segments(np.ones(len(x), bool), FS, 1.0, 0.5, 8)
    f, p = spectral.masked_welch(x, FS, plan, "hann")
    t = tonal.detect_tones(f, p, "hann", spectral.window_metrics("hann", plan.nperseg).enbw_hz(FS), 10, 20, 20000, 1)
    v.append({"id": "TV-001", "inv": "INV-004", "input": "sine(f=1001.3 Hz, A=0.3, 10 s, fs=48 kHz), hann, 1 Hz target",
              "quantity": "tone power (FS^2)", "reference": "closed form A^2/2", "expected": 0.045, "computed": t[0]["power"],
              "rtol": 0.01, "physical_uncertainty": "n/a (synthetic)"})
    # TV-002 Parseval white noise
    w = signals.white_noise(0.1, 20.0, FS, seed=42)
    f, p = spectral.masked_welch(w, FS, spectral.plan_segments(np.ones(len(w), bool), FS, 1.0, 0.5, 8))
    v.append({"id": "TV-002", "inv": "INV-003", "input": "white_noise(rms=0.1, 20 s, seed=42)", "quantity": "sum(PSD)*df / var(x)",
              "reference": "Parseval identity = 1", "expected": 1.0, "computed": float(np.sum(p) * (f[1] - f[0]) / np.var(w)),
              "rtol": 0.02, "physical_uncertainty": "estimator variance ~ 1/sqrt(n_avg*bins)"})
    # TV-003..007 ENBW in bins (closed-form windows, N=4096)
    for i, (name, ref) in enumerate([("hann", 1.5), ("hamming", 1.36283), ("boxcar", 1.0), ("blackmanharris", 2.00435), ("flattop", 3.77)]):
        m = spectral.window_metrics(name, 4096)
        v.append({"id": f"TV-{3 + i:03d}", "inv": "INV-004", "input": f"{name} window, N=4096 (periodic)", "quantity": "ENBW (bins)",
                  "reference": "N*sum(w^2)/sum(w)^2 (published values)", "expected": ref, "computed": m.enbw_bins, "rtol": 0.003,
                  "physical_uncertainty": "n/a"})
    # TV-008 phase sign
    y = signals.delay(w, 0.0005, FS)
    f, pxx, pyy, pxy = spectral.masked_csd(w, y, FS, spectral.plan_segments(np.ones(len(w), bool), FS, 10.0, 0.5, 8))
    _, h1, _ = cross.coherence_and_transfer(pxx, pyy, pxy)
    k = int(np.argmin(np.abs(f - 200)))
    v.append({"id": "TV-008", "inv": "INV-005", "input": "y = x delayed 0.5 ms; H1 = Pxy/Pxx at ~200 Hz", "quantity": "phase (rad)",
              "reference": "-2*pi*f*tau", "expected": -2 * math.pi * f[k] * 0.0005, "computed": float(np.angle(h1[k])), "atol": 0.02,
              "physical_uncertainty": "n/a"})
    # TV-009..011 coherence thresholds
    for i, n in enumerate((1, 8, 32)):
        ref = 1.0 if n < 2 else 1 - 0.05 ** (1 / (n - 1))
        v.append({"id": f"TV-{9 + i:03d}", "inv": "INV-011/ADV-009", "input": f"n_eff={n}, alpha=0.05", "quantity": "coherence threshold",
                  "reference": "1 - alpha^(1/(n-1))", "expected": ref, "computed": cross.coherence_threshold(n, 0.05), "rtol": 1e-12,
                  "physical_uncertainty": "n/a"})
    # TV-012 SPL reference
    from sonicclue.domain import units

    v.append({"id": "TV-012", "inv": "INV-001", "input": "94 dB SPL", "quantity": "Pa RMS", "reference": "20e-6 * 10^(94/20)",
              "expected": 1.0023744672545445, "computed": units.spl_db_to_pa(94.0), "rtol": 1e-12, "physical_uncertainty": "calibrator class"})
    return v


def check(v: dict) -> bool:
    if "rtol" in v:
        return abs(v["computed"] - v["expected"]) <= v["rtol"] * abs(v["expected"])
    return abs(v["computed"] - v["expected"]) <= v["atol"]


if __name__ == "__main__":
    vecs = compute()
    bad = [x["id"] for x in vecs if not check(x)]
    if "--check" in sys.argv:
        print(f"{len(vecs) - len(bad)}/{len(vecs)} vectors within tolerance", *bad)
        sys.exit(1 if bad else 0)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(vecs, indent=2) + "\n")
    print(f"wrote {OUT} ({len(vecs)} vectors, {len(bad)} failing)")

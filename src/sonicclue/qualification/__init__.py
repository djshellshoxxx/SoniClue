"""Hardware qualification and runtime self-test (docs/specs/18-hardware-qualification.md).

* ``selftest()``: numerical checks on the installed build (Parseval, tone
  power, phase sign, coherence threshold, band additivity). These verify
  that the bundled numerical stack behaves correctly on this machine. They do
  NOT qualify any audio hardware.
* ``loopback_test()``: plays known signals through an output-to-input cable
  and measures frequency accuracy, level linearity, noise floor, latency and
  dropouts. Only a pass on real hardware may mark a device QUALIFIED in the
  qualification matrix. A pass on the simulated backend is recorded as
  "SIMULATED" and never as QUALIFIED.
* The matrix (workspace ``qualification.json``) lists every device/OS
  combination tested. Untested combinations are UNQUALIFIED.
"""

from __future__ import annotations

import json
import math
import platform
import threading
import time
from pathlib import Path

import numpy as np

from .. import BUILD_ID, __version__
from ..domain.model import utcnow
from ..dsp import cross, signals, spectral, tonal
from ..storage.files import atomic_write_text

QUALIFIED, UNQUALIFIED, FAILED, SIMULATED = "QUALIFIED", "UNQUALIFIED", "FAILED", "SIMULATED"


def selftest() -> list[dict]:
    fs = 48000.0
    out = []

    def rec(name, ok, detail):
        out.append({"name": name, "passed": bool(ok), "detail": detail})

    x = signals.white_noise(0.1, 10, fs, seed=1)
    plan = spectral.plan_segments(np.ones(len(x), bool), fs, 2.0, 0.5, 8)
    f, p = spectral.masked_welch(x, fs, plan)
    ratio = float(np.sum(p) * (f[1] - f[0]) / np.var(x))
    rec("parseval", abs(ratio - 1) < 0.02, f"sum(PSD)*df / var = {ratio:.4f}")
    s = signals.sine(997.0, 0.25, 10, fs)
    f, p = spectral.masked_welch(s, fs, plan)
    t = tonal.detect_tones(f, p, "hann", spectral.window_metrics("hann", plan.nperseg).enbw_hz(fs), 10, 20, 20000, 1)
    err = abs(10 * math.log10(t[0]["power"] / (0.25**2 / 2))) if t else 99
    rec("tone_power", err < 0.05, f"tone power error {err:.3f} dB")
    y = signals.delay(x, 0.001, fs)
    f, pxx, pyy, pxy = spectral.masked_csd(x, y, fs, plan)
    _, h1, _ = cross.coherence_and_transfer(pxx, pyy, pxy)
    k = int(np.argmin(np.abs(f - 100)))
    rec("phase_sign", abs(np.angle(h1[k]) + 2 * np.pi * f[k] * 0.001) < 0.05, f"phase at {f[k]:.0f} Hz = {np.angle(h1[k]):.3f} rad")
    rec("coherence_threshold", cross.coherence_threshold(1, 0.05) == 1.0 and 0 < cross.coherence_threshold(16, 0.05) < 0.25,
        "single-average threshold is 1; n=16 threshold < 0.25")
    a = spectral.integrate_band(f, p, 100, 300) + spectral.integrate_band(f, p, 300, 700)
    rec("band_additivity", abs(a - spectral.integrate_band(f, p, 100, 700)) < 1e-12 * max(a, 1e-30), "adjacent bands sum to union")
    return out


def loopback_test(backend, out_device: int, in_device: int, samplerate: float = 48000.0, in_channel: int = 0,
                  in_channels: int = 1) -> dict:
    """Play a 1 kHz sine at -20/-30/-40 dBFS and a sweep via loopback; analyse what comes back."""
    from ..acquisition.session import CaptureSession

    results = {}
    blocks: list[np.ndarray] = []

    class Sink:
        def write(self, b):
            blocks.append(b.copy())

        def close(self):
            return []

    levels = [-20.0, -30.0, -40.0]
    dur = 2.0
    stim = np.concatenate([signals.sine(1000.0, 10 ** (lv / 20), dur, samplerate) for lv in levels]
                          + [np.zeros(int(samplerate))]).astype(np.float32)
    pos = {"i": 0}
    done = threading.Event()

    def fill(n):
        i = pos["i"]
        chunk = np.zeros(n, np.float32)
        m = max(0, min(n, len(stim) - i))
        chunk[:m] = stim[i : i + m]
        pos["i"] += n
        if pos["i"] >= len(stim):
            done.set()
        return chunk

    sess = CaptureSession(backend, in_device, samplerate, in_channels, Sink(), duration_s=len(stim) / samplerate + 1.0)
    sess.start()
    out = backend.open_output(out_device, samplerate, 1, 1024, fill, lambda e: done.set())
    t0 = time.monotonic()
    out.start()
    done.wait(len(stim) / samplerate + 5)
    out.stop()
    out.close()
    oc = sess.wait(timeout=30)
    rx = np.concatenate(blocks)[:, in_channel] if blocks else np.zeros(1)
    results["duration_s"] = round(time.monotonic() - t0, 2)
    results["dropouts"] = len(oc.gaps)
    d, amb = cross.estimate_delay(stim[: len(rx)], rx[: len(stim)], samplerate, max_lag_s=0.5)
    results["latency_ms"] = None if d is None else round(d * 1000, 2)
    meas = []
    shift = int((d or 0) * samplerate)
    for i, lv in enumerate(levels):
        a = shift + int((i * dur + 0.5) * samplerate)
        seg = rx[a : a + int(samplerate)]
        if len(seg) < samplerate / 2:
            meas.append(None)
            continue
        pl = spectral.plan_segments(np.ones(len(seg), bool), samplerate, 2.0, 0.5, 4)
        f, p = spectral.masked_welch(seg, samplerate, pl)
        tt = tonal.detect_tones(f, p, "hann", spectral.window_metrics("hann", pl.nperseg).enbw_hz(samplerate), 10, 900, 1100, 1)
        meas.append((tt[0]["freq_hz"], 10 * math.log10(tt[0]["power"])) if tt else None)
    ok_meas = [m for m in meas if m]
    results["freq_error_hz"] = round(max(abs(m[0] - 1000) for m in ok_meas), 3) if ok_meas else None
    if len(ok_meas) == 3:
        steps = [ok_meas[0][1] - ok_meas[1][1], ok_meas[1][1] - ok_meas[2][1]]
        results["linearity_error_db"] = round(max(abs(s - 10) for s in steps), 3)
    else:
        results["linearity_error_db"] = None
    tail = rx[-int(0.5 * samplerate):]
    results["noise_floor_dbfs"] = round(20 * math.log10(max(float(np.std(tail)), 1e-12)), 1)
    passed = (results["dropouts"] == 0 and results["freq_error_hz"] is not None and results["freq_error_hz"] < 0.5
              and results["linearity_error_db"] is not None and results["linearity_error_db"] < 0.5)
    results["passed"] = bool(passed)
    return results


class QualificationMatrix:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.records: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            recs = json.loads(self.path.read_text())
            if isinstance(recs, list):
                return recs
        except (ValueError, OSError):
            pass
        try:  # corrupt: keep the damaged file for inspection and start empty
            self.path.replace(self.path.with_suffix(".corrupt"))
        except OSError:
            pass
        return []

    def add(self, device: str, backend: str, results: dict, simulated: bool) -> dict:
        status = SIMULATED if simulated else (QUALIFIED if results.get("passed") else FAILED)
        rec = {"device": device, "backend": backend, "os": f"{platform.system()} {platform.release()}", "arch": platform.machine(),
               "build": f"{__version__}+{BUILD_ID}", "date": utcnow().isoformat(), "status": status, "results": results}
        self.records.append(rec)
        atomic_write_text(self.path, json.dumps(self.records, indent=1))
        return rec

    def status(self, device: str) -> str:
        osname = f"{platform.system()} {platform.release()}"
        recs = [r for r in self.records if r["device"] == device and r["os"] == osname]
        return recs[-1]["status"] if recs else UNQUALIFIED

    def statuses(self) -> dict[str, str]:
        return {r["device"]: self.status(r["device"]) for r in self.records}

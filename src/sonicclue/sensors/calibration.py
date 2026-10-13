"""Sensor calibration: creating profiles, checking validity, applying corrections.

Conventions (INV-006, docs/specs/06-sensors-and-calibration.md):

* physical = FS / sensitivity_fs_per_unit.
* fr_correction is the dB to ADD to a measured level to get the true level.
  A manufacturer "response" file lists the sensor's deviation from flat, so
  importing one stores the *negated* values (``parse_fr_file(kind="response")``).
* A profile is valid for a channel only when sensor ids match, it has not
  expired, and the interface gain matches the reference gain within
  GAIN_TOLERANCE_DB. If either gain is unknown, the profile is used with a
  warning, because the user has not confirmed the gain is unchanged.
* Contact pickups and piezo discs cannot be calibrated to physical units
  (their output depends on mounting, bending and airborne pickup), so a
  calibration attempt raises SC_CALIBRATION.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from ..domain.errors import CalibrationError
from ..domain.model import (
    RELATIVE_ONLY_KINDS,
    CalibrationProfile,
    ChannelConfig,
    FrPoint,
    QualityCode,
    QualityFlag,
    SensorDescriptor,
    Severity,
    utcnow,
)
from ..domain.units import Quantity, spl_db_to_pa
from ..dsp import levels, spectral, tonal

GAIN_TOLERANCE_DB = 0.1
MIN_CAL_TONE_PROMINENCE_DB = 30.0
MAX_CAL_INSTABILITY_DB = 0.2


@dataclass
class CalStatus:
    usable: bool
    flags: list[QualityFlag] = field(default_factory=list)


def evaluate(profile: CalibrationProfile | None, channel: ChannelConfig, sensor: SensorDescriptor | None,
             now: datetime | None = None) -> CalStatus:
    now = now or utcnow()
    ch = channel.index
    if profile is None:
        return CalStatus(False, [QualityFlag(code=QualityCode.CAL_MISSING, severity=Severity.INFO, channel=ch,
                                             message="no calibration: levels are relative (dBFS), not physical")])
    flags: list[QualityFlag] = []
    if sensor is not None and sensor.kind in RELATIVE_ONLY_KINDS:
        return CalStatus(False, [QualityFlag(code=QualityCode.CAL_MISSING, severity=Severity.WARNING, channel=ch,
                                             message=f"{sensor.kind.value} cannot carry a physical calibration; using relative levels")])
    if channel.sensor_id and profile.sensor_id != channel.sensor_id:
        return CalStatus(False, [QualityFlag(code=QualityCode.CAL_MISSING, severity=Severity.WARNING, channel=ch,
                                             message=f"calibration {profile.id} belongs to sensor {profile.sensor_id}, not {channel.sensor_id}")])
    if profile.expires_utc and now > profile.expires_utc:
        return CalStatus(False, [QualityFlag(code=QualityCode.CAL_EXPIRED, severity=Severity.WARNING, channel=ch,
                                             message=f"calibration {profile.id} expired {profile.expires_utc.date()}")])
    if profile.reference_gain_db is not None and channel.input_gain_db is not None:
        if abs(profile.reference_gain_db - channel.input_gain_db) > GAIN_TOLERANCE_DB:
            return CalStatus(False, [QualityFlag(
                code=QualityCode.CAL_GAIN_MISMATCH, severity=Severity.INVALID, channel=ch,
                message=f"interface gain {channel.input_gain_db:+.1f} dB differs from calibration gain "
                        f"{profile.reference_gain_db:+.1f} dB: recalibrate (levels shown as relative)")])
    else:
        flags.append(QualityFlag(code=QualityCode.CAL_GAIN_MISMATCH, severity=Severity.WARNING, channel=ch,
                                 message="interface gain not recorded for both calibration and capture; "
                                         "absolute levels assume the gain is unchanged"))
    return CalStatus(True, flags)


def fr_correction_db(profile: CalibrationProfile, freqs: np.ndarray) -> np.ndarray:
    """Correction (dB to add) at each frequency: NaN outside ``valid_band_hz``,
    0 where the profile has no correction curve."""
    out = np.zeros_like(freqs, dtype=float)
    lo, hi = profile.valid_band_hz
    if profile.fr_correction:
        fx = np.log10([p.freq_hz for p in profile.fr_correction])
        gx = np.array([p.correction_db for p in profile.fr_correction])
        with np.errstate(divide="ignore"):
            lf = np.log10(np.maximum(freqs, 1e-9))
        out = np.interp(lf, fx, gx)
    out[(freqs < lo) | (freqs > hi)] = np.nan
    return out


def parse_fr_file(text: str, kind: str) -> tuple[list[FrPoint], float | None]:
    """Parse 'freq dB' lines (whitespace, comma or tab separated). Lines starting
    with '*', '#' or '"' are headers. Returns (points as corrections, sensitivity
    factor dB if a 'Sens Factor' header is present). ``kind``: "response" (sensor
    deviation; negated on import) or "correction" (already dB to add)."""
    if kind not in ("response", "correction"):
        raise CalibrationError("kind must be 'response' or 'correction'")
    pts: dict[float, float] = {}
    sens = None
    for raw in text.splitlines()[:20000]:
        line = raw.strip()
        if not line:
            continue
        if line[0] in "*#\"":
            low = line.lower()
            if "sens factor" in low:
                try:
                    sens = float(low.split("=")[1].split("db")[0])
                except (IndexError, ValueError):
                    pass
            continue
        parts = line.replace(",", " ").replace("\t", " ").split()
        try:
            fq, g = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            raise CalibrationError(f"unparseable calibration line: {line[:60]!r}") from None
        if fq <= 0 or not math.isfinite(g) or abs(g) > 60:
            raise CalibrationError(f"invalid calibration point {fq} Hz {g} dB")
        pts[fq] = -g if kind == "response" else g
    if len(pts) < 2:
        raise CalibrationError("calibration file needs at least two points")
    return [FrPoint(freq_hz=f, correction_db=pts[f]) for f in sorted(pts)], sens


def calibrate_from_tone(x_fs: np.ndarray, fs: float, sensor: SensorDescriptor, reference_level: float,
                        reference_freq_hz: float, *, gain_db: float | None, device_name: str = "",
                        capture_id: str | None = None, calibrator_uncertainty_db: float = 0.4,
                        valid_band_hz: tuple[float, float] | None = None, expires_utc: datetime | None = None) -> CalibrationProfile:
    """Derive sensitivity from a recording of a reference calibrator.

    ``reference_level``: dB SPL for sound pressure (e.g. 94 or 114) or RMS m/s^2
    for acceleration (e.g. 10 m/s^2 at 159.2 Hz). The calibration is rejected
    when the tone is missing, clipped, too close to the noise, or unstable."""
    if sensor.kind in RELATIVE_ONLY_KINDS:
        raise CalibrationError(f"{sensor.kind.value} sensors cannot be calibrated to physical units", code="SC_CAL_RELATIVE_ONLY")
    if sensor.quantity is Quantity.SOUND_PRESSURE:
        ref_rms = spl_db_to_pa(reference_level)
    elif sensor.quantity in (Quantity.ACCELERATION, Quantity.VELOCITY, Quantity.VOLTAGE):
        ref_rms = float(reference_level)
    else:
        raise CalibrationError("sensor quantity must be physical")
    if ref_rms <= 0:
        raise CalibrationError("reference level must be positive")
    scr = levels.screen_channel(x_fs, fs, 0)
    if scr.clipped_samples:
        raise CalibrationError("calibration recording is clipped: reduce gain and repeat", code="SC_CAL_CLIPPED")
    plan = spectral.plan_segments(scr.valid, fs, 2.0, 0.5, 8)
    if plan is None or len(x_fs) < fs * 2:
        raise CalibrationError("calibration recording must be at least 2 s long", code="SC_CAL_SHORT")
    f, p = spectral.masked_welch(x_fs, fs, plan)
    wm = spectral.window_metrics("hann", plan.nperseg)
    tones = tonal.detect_tones(f, p, "hann", wm.enbw_hz(fs), 10.0, reference_freq_hz * 0.97, reference_freq_hz * 1.03, 1)
    if not tones:
        raise CalibrationError(f"no calibrator tone found near {reference_freq_hz:g} Hz", code="SC_CAL_NO_TONE")
    t = tones[0]
    if t["prominence_db"] < MIN_CAL_TONE_PROMINENCE_DB:
        raise CalibrationError(f"calibrator tone only {t['prominence_db']:.0f} dB above noise (need {MIN_CAL_TONE_PROMINENCE_DB:.0f})",
                               code="SC_CAL_LOW_SNR")
    # stability: tone level in quarters of the recording
    quarter = len(x_fs) // 4
    lv = []
    for i in range(4):
        seg = x_fs[i * quarter : (i + 1) * quarter]
        pl = spectral.plan_segments(np.ones(len(seg), bool), fs, 2.0, 0.5, 2)
        if pl is None:
            continue
        ff, pp = spectral.masked_welch(seg, fs, pl)
        tq = tonal.detect_tones(ff, pp, "hann", spectral.window_metrics("hann", pl.nperseg).enbw_hz(fs), 6.0,
                                reference_freq_hz * 0.97, reference_freq_hz * 1.03, 1)
        if tq:
            lv.append(10 * math.log10(tq[0]["power"]))
    spread = (max(lv) - min(lv)) if len(lv) >= 2 else 0.0
    if len(lv) < 4 or spread > MAX_CAL_INSTABILITY_DB:
        raise CalibrationError(f"calibrator level unstable ({spread:.2f} dB across the recording)", code="SC_CAL_UNSTABLE")
    sensitivity = t["rms"] / ref_rms
    unc = math.sqrt(calibrator_uncertainty_db**2 + (spread / 2) ** 2 + 0.05**2)
    band = valid_band_hz or (sensor.usable_band_hz or (20.0, min(20000.0, 0.45 * fs)))
    return CalibrationProfile(
        id=f"cal-{uuid.uuid4().hex[:10]}", sensor_id=sensor.id, quantity=sensor.quantity,
        sensitivity_fs_per_unit=float(sensitivity), reference_freq_hz=float(t["freq_hz"]),
        reference_gain_db=gain_db, valid_band_hz=(float(band[0]), float(band[1])),
        uncertainty_db=round(unc, 3), method="calibrator", source_capture_id=capture_id, device_name=device_name,
        created_utc=utcnow(), expires_utc=expires_utc,
        notes=f"reference {reference_level:g} at {reference_freq_hz:g} Hz; measured tone {t['freq_hz']:.2f} Hz, "
              f"SNR {t['prominence_db']:.0f} dB, stability {spread:.3f} dB",
    )


def profile_from_datasheet(sensor: SensorDescriptor, sensitivity_v_per_unit: float, interface_fs_vrms: float, *,
                           gain_db: float | None, reference_freq_hz: float = 1000.0,
                           fr_points: list[FrPoint] | None = None, uncertainty_db: float = 2.0,
                           valid_band_hz: tuple[float, float] = (20.0, 20000.0)) -> CalibrationProfile:
    """Nominal profile from datasheet values. ``interface_fs_vrms`` is the RMS
    input voltage giving a full-scale sine RMS (1/sqrt(2) FS) at ``gain_db``.
    Datasheet tolerances are large, so the default uncertainty is 2 dB; this
    method is VALIDATION_REQUIRED per DEC-007."""
    if sensor.kind in RELATIVE_ONLY_KINDS:
        raise CalibrationError(f"{sensor.kind.value} sensors cannot be calibrated", code="SC_CAL_RELATIVE_ONLY")
    if sensitivity_v_per_unit <= 0 or interface_fs_vrms <= 0:
        raise CalibrationError("sensitivity and interface full scale must be positive")
    sens_fs = sensitivity_v_per_unit * (1 / math.sqrt(2)) / interface_fs_vrms
    return CalibrationProfile(
        id=f"cal-{uuid.uuid4().hex[:10]}", sensor_id=sensor.id, quantity=sensor.quantity,
        sensitivity_fs_per_unit=sens_fs, reference_freq_hz=reference_freq_hz, reference_gain_db=gain_db,
        fr_correction=fr_points or [], valid_band_hz=valid_band_hz, uncertainty_db=uncertainty_db,
        method="manufacturer_sheet", created_utc=utcnow(),
    )

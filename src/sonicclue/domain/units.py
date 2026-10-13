"""Physical quantities, units and decibel references.

Conventions (docs/specs/08-dsp-and-numerical-methods.md section 2, INV-001..INV-003):

* Raw samples are in **FS**: digital full scale, so +/-1.0 is the converter's
  clipping point. A full-scale sine has RMS 1/sqrt(2), which is -3.01 dBFS
  under the RMS convention used here (dBFS = 20*log10(rms_FS)).
* A calibration profile maps FS to a physical unit through
  ``physical = FS / sensitivity_fs_per_unit`` (INV-006).
* Level references: sound pressure re 20 uPa (ISO 1683), acceleration
  re 1e-6 m/s^2 (ISO 1683), velocity re 1e-9 m/s (ISO 1683), voltage re 1 V.
* ``RELATIVE`` quantities (uncalibrated microphones, contact pickups, piezo
  discs) stay in FS and are labelled dBFS. They are never presented as
  physical values.
"""

from __future__ import annotations

import math
from enum import Enum


class Quantity(str, Enum):
    SOUND_PRESSURE = "sound_pressure"
    ACCELERATION = "acceleration"
    VELOCITY = "velocity"
    VOLTAGE = "voltage"
    RELATIVE = "relative"


UNIT = {
    Quantity.SOUND_PRESSURE: "Pa",
    Quantity.ACCELERATION: "m/s^2",
    Quantity.VELOCITY: "m/s",
    Quantity.VOLTAGE: "V",
    Quantity.RELATIVE: "FS",
}

DB_REFERENCE = {
    Quantity.SOUND_PRESSURE: 20e-6,
    Quantity.ACCELERATION: 1e-6,
    Quantity.VELOCITY: 1e-9,
    Quantity.VOLTAGE: 1.0,
    Quantity.RELATIVE: 1.0,
}

DB_LABEL = {
    Quantity.SOUND_PRESSURE: "dB re 20 uPa",
    Quantity.ACCELERATION: "dB re 1 um/s^2",
    Quantity.VELOCITY: "dB re 1 nm/s",
    Quantity.VOLTAGE: "dBV",
    Quantity.RELATIVE: "dBFS",
}

# Floor used when converting zero power to dB, so silence gives a finite,
# recognisable value instead of -inf. Values at or below it are reported as
# "below floor" by the callers that care (EDGE-001).
DB_FLOOR = -300.0


def amplitude_db(rms: float, quantity: Quantity) -> float:
    """RMS amplitude to dB using the quantity's ISO reference."""
    ref = DB_REFERENCE[quantity]
    if not math.isfinite(rms) or rms <= 0:
        return DB_FLOOR
    return max(DB_FLOOR, 20.0 * math.log10(rms / ref))


def power_db(power: float, quantity: Quantity) -> float:
    """Mean-square value (unit^2) to dB using the quantity's ISO reference."""
    ref = DB_REFERENCE[quantity]
    if not math.isfinite(power) or power <= 0:
        return DB_FLOOR
    return max(DB_FLOOR, 10.0 * math.log10(power / (ref * ref)))


def db_to_power(level_db: float, quantity: Quantity) -> float:
    ref = DB_REFERENCE[quantity]
    return (ref * ref) * 10.0 ** (level_db / 10.0)


def spl_db_to_pa(level_db: float) -> float:
    """Sound pressure level to RMS pascals. 94 dB SPL is about 1.0024 Pa."""
    return 20e-6 * 10.0 ** (level_db / 20.0)

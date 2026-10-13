"""Capability tiers (docs/specs/06-sensors-and-calibration.md section 4).

The tier is a summary of what the current sensor set can *legitimately*
support. It is not a paid edition. Each capability is computed explicitly,
and analyses check capabilities rather than the tier number.

| Tier | Sensors                                  | Legitimate use                                       |
|------|------------------------------------------|------------------------------------------------------|
| 1    | microphone only (uncalibrated)           | relative dBFS levels, spectra, on/off comparisons    |
| 2    | microphone + contact pickup              | adds relative vibration presence; no physical units  |
| 3    | microphone + accelerometer               | adds vibration spectra (physical only if calibrated) |
| 4    | multiple synchronized sensors            | adds coherence, transfer functions, delays           |
| 5    | calibrated sensors (valid profiles)      | adds absolute SPL / m/s^2 with stated uncertainty    |
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.model import ACOUSTIC_KINDS, ChannelConfig, SensorDescriptor, SensorKind

ACCEL_KINDS = {SensorKind.ANALOG_ACCELEROMETER, SensorKind.MEMS_ACCELEROMETER}
CONTACT_KINDS = {SensorKind.CONTACT_PICKUP, SensorKind.PIEZO_DISC}


@dataclass(frozen=True)
class Capabilities:
    tier: int
    relative_levels: bool
    absolute_levels: bool
    vibration_relative: bool
    vibration_physical: bool
    synchronized_cross_channel: bool
    notes: tuple[str, ...]


def capabilities(channels: list[ChannelConfig], sensors: dict[str, SensorDescriptor], calibrated: set[int],
                 shared_clock: bool = True) -> Capabilities:
    kinds = {ch.index: (sensors[ch.sensor_id].kind if ch.sensor_id in sensors else SensorKind.OTHER) for ch in channels}
    has_acoustic = any(k in ACOUSTIC_KINDS for k in kinds.values())
    has_contact = any(k in CONTACT_KINDS for k in kinds.values())
    has_accel = any(k in ACCEL_KINDS for k in kinds.values())
    accel_cal = any(k in ACCEL_KINDS and i in calibrated for i, k in kinds.items())
    sync = shared_clock and len(channels) >= 2
    notes = []
    if not has_acoustic:
        notes.append("no microphone: the acoustic receiver is not measured directly")
    if has_contact:
        notes.append("contact pickups give relative vibration only; they also respond to airborne sound")
    if not calibrated:
        notes.append("no valid calibration: levels are relative (dBFS)")
    if len(channels) >= 2 and not shared_clock:
        notes.append("channels are not on a shared clock: coherence and transfer functions disabled")
    tier = 1
    if has_contact:
        tier = 2
    if has_accel:
        tier = 3
    if sync and (has_contact or has_accel or len(channels) >= 2):
        tier = 4
    if calibrated:
        tier = 5
    return Capabilities(tier, True, bool(calibrated), has_contact or has_accel, accel_cal, sync, tuple(notes))

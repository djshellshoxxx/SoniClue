"""Comparability checks between captures (docs/specs/09 section 5; ADV-004, ADV-005, ADV-008).

The rules decide whether a level difference between two captures can be
attributed to the condition that changed (equipment state, intervention)
rather than to the measurement changing. "invalidates" blocks the comparison
from being used as evidence. "caveat" is shown to the user but does not block.

| Context change                                  | Effect      | Reason |
|-------------------------------------------------|-------------|--------|
| simulated vs physical data                      | invalidates | not the same world |
| different sensor                                | invalidates | different sensitivity/response |
| position id / location / distance (>10%) differ | invalidates | ADV-008: quieter can just mean farther |
| mounting differs                                | invalidates | ADV-004: mount changes the transfer path |
| orientation differs                             | invalidates | directivity / axis |
| interface gain differs (uncalibrated)           | invalidates | levels scale with gain |
| interface gain differs (both calibrated)        | caveat      | calibration absorbs gain only if re-validated |
| AGC on or unknown in either capture             | invalidates | ADV-005: AGC rescales levels |
| processing (HPF, enhancements) differs          | invalidates | spectral shaping |
| invalid quality flag (clipping, silence ...)    | invalidates | data unusable |
| measurement setup changed by intervention       | invalidates | confounded with measurement |
| device differs                                  | caveat      | converter response may differ |
| sample rate differs                             | caveat      | comparison restricted to common band |
| calibration profile differs                     | caveat      | |
| position/gain not recorded                      | caveat      | comparability cannot be verified |
"""

from __future__ import annotations

from ..domain.model import AnalysisResult, CaptureManifest, ComparabilityIssue, Severity

LEVEL_INVALIDATING_CODES = {"clipping", "silence", "agc_active", "cal_gain_mismatch", "short_capture", "nonfinite"}


def _ch(m: CaptureManifest, label: str):
    return next((c for c in m.channels if c.label == label), None)


def _issue(field, a, b, effect, msg):
    return ComparabilityIssue(field=field, a=str(a), b=str(b), effect=effect, message=msg)


def check(ma: CaptureManifest, mb: CaptureManifest, label: str, aa: AnalysisResult | None = None,
          ab: AnalysisResult | None = None) -> list[ComparabilityIssue]:
    out: list[ComparabilityIssue] = []
    ca, cb = _ch(ma, label), _ch(mb, label)
    if ca is None or cb is None:
        return [_issue("channel", ca.label if ca else "-", cb.label if cb else "-", "invalidates",
                       f"channel '{label}' missing in one capture")]
    if (ma.source == "simulated") != (mb.source == "simulated"):
        out.append(_issue("source", ma.source, mb.source, "invalidates", "cannot compare simulated with physical data"))
    if ca.sensor_id != cb.sensor_id:
        out.append(_issue("sensor", ca.sensor_id, cb.sensor_id, "invalidates", "different sensor"))
    pa, pb = ca.placement, cb.placement
    if pa.position_id and pb.position_id and pa.position_id != pb.position_id:
        out.append(_issue("position_id", pa.position_id, pb.position_id, "invalidates",
                          "sensor position changed: a level change may be caused by the move (ADV-008)"))
    elif pa.location and pb.location and pa.location.strip().lower() != pb.location.strip().lower():
        out.append(_issue("location", pa.location, pb.location, "invalidates", "sensor location description changed"))
    if pa.distance_m is not None and pb.distance_m is not None:
        if abs(pa.distance_m - pb.distance_m) > 0.1 * max(pa.distance_m, pb.distance_m, 1e-3):
            out.append(_issue("distance_m", pa.distance_m, pb.distance_m, "invalidates",
                              "source distance changed by more than 10%"))
    if not (pa.position_id or pa.location) or not (pb.position_id or pb.location):
        out.append(_issue("position", pa.position_id or pa.location or "unrecorded", pb.position_id or pb.location or "unrecorded",
                          "caveat", "sensor position not recorded for both captures; keep the sensor fixed"))
    if pa.mounting != pb.mounting:
        out.append(_issue("mounting", pa.mounting.value, pb.mounting.value, "invalidates",
                          "sensor mounting changed (ADV-004)"))
    if pa.orientation and pb.orientation and pa.orientation != pb.orientation:
        out.append(_issue("orientation", pa.orientation, pb.orientation, "invalidates", "sensor orientation changed"))
    cal_a = aa is not None and any(c.calibrated for c in aa.channels if c.label == label)
    cal_b = ab is not None and any(c.calibrated for c in ab.channels if c.label == label)
    if ca.input_gain_db is not None and cb.input_gain_db is not None:
        if abs(ca.input_gain_db - cb.input_gain_db) > 0.1:
            out.append(_issue("input_gain_db", ca.input_gain_db, cb.input_gain_db, "caveat" if (cal_a and cal_b) else "invalidates",
                              "interface gain changed" + ("" if (cal_a and cal_b) else ": relative levels are not comparable")))
    else:
        out.append(_issue("input_gain_db", ca.input_gain_db, cb.input_gain_db, "caveat",
                          "interface gain not recorded; it must not change between captures"))
    for nm, c in (("A", ca), ("B", cb)):
        if c.agc != "off":
            out.append(_issue("agc", ca.agc, cb.agc, "invalidates",
                              f"automatic gain control is {c.agc} in capture {nm}: confirm it is OFF (ADV-005)"))
            break
    if sorted(ca.processing) != sorted(cb.processing):
        out.append(_issue("processing", ",".join(ca.processing), ",".join(cb.processing), "invalidates",
                          "input processing changed"))
    if ma.device.name != mb.device.name:
        out.append(_issue("device", ma.device.name, mb.device.name, "caveat", "different audio interface"))
    if abs(ma.sample_rate_hz - mb.sample_rate_hz) > 0.5:
        out.append(_issue("sample_rate_hz", ma.sample_rate_hz, mb.sample_rate_hz, "caveat",
                          "different sample rates: compared over the common band only"))
    if ca.calibration_id != cb.calibration_id and (ca.calibration_id or cb.calibration_id):
        out.append(_issue("calibration", ca.calibration_id, cb.calibration_id, "caveat", "different calibration profiles"))
    for nm, an in (("A", aa), ("B", ab)):
        if an is None:
            continue
        for chn in an.channels:
            if chn.label != label:
                continue
            bad = [q for q in chn.quality if q.severity is Severity.INVALID and q.code.value in LEVEL_INVALIDATING_CODES]
            if bad:
                out.append(_issue("quality", nm, bad[0].code.value, "invalidates", f"capture {nm}: {bad[0].message}"))
    iv = mb.context.intervention
    if iv and iv.changes_measurement_setup:
        out.append(_issue("intervention", "-", iv.description, "invalidates",
                          "the intervention changed the measurement setup itself"))
    return out


def merge(issues: list[ComparabilityIssue]) -> list[ComparabilityIssue]:
    seen, out = set(), []
    for i in issues:
        key = (i.field, i.a, i.b, i.effect)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out

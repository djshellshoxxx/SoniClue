"""Next-test recommendation (docs/specs/09-diagnostic-reasoning.md section 7).

For every candidate test (a procedure plus parameters), each *open*
hypothesis (not strongly supported, not contradicted) gets a predicted
outcome, or None when the test says nothing about it. The test's value is

    pairs separated = number of open-hypothesis pairs with different predictions
    direct          = number of open hypotheses the test bears on
    score           = (2*pairs + direct) / difficulty

This is a transparent, count-based stand-in for expected information gain.
It needs no probabilities, which SonicClue cannot justify (DEC-011). Tests
that separate nothing are listed as not useful now rather than recommended.
Availability checks hardware (tier, sensor kinds, output device for
stimulus tests) and required parameters.
"""

from __future__ import annotations

from itertools import combinations

from ..domain.model import (
    ACOUSTIC_KINDS,
    SUPPORT_ORDER,
    VIBRATION_KINDS,
    Hypothesis,
    HypothesisCategory,
    NextTest,
    SupportLevel,
)
from .. import procedures

ELECTRIC_KINDS = {"power", "amplifier", "lighting", "computer", "appliance"}


def _open(h: Hypothesis) -> bool:
    return h.level not in (SupportLevel.STRONG, SupportLevel.CONTRADICTED)


def recommend(inp, hyps: list[Hypothesis], conclusion: str, limit: int = 6) -> list[NextTest]:
    case = inp.case
    kinds = {s.kind for s in case.sensors}
    has_vib = bool(kinds & VIBRATION_KINDS)
    has_ac = bool(kinds & ACOUSTIC_KINDS) or not kinds
    eq = {e.id: e for e in case.equipment}
    open_h = [h for h in hyps if _open(h)]
    out: list[tuple[float, NextTest]] = []

    done = {(r.procedure_id, tuple(sorted(r.params.items()))) for r in inp.runs if r.state == "completed"}

    def add(pid: str, params: dict, preds: dict[str, str | None], reason_extra: str = "", indirect: set[str] = frozenset()):
        """``indirect``: hypotheses with a prediction that only matters in contrast
        with a directly tested one (e.g. "no drop" for other sources in an on/off test)."""
        d = procedures.get(pid)
        pr = {h.id: preds.get(h.id) for h in open_h}
        bearing = [h for h in open_h if pr.get(h.id)]
        direct_h = [h for h in bearing if h.id not in indirect]
        pairs = [(a, b) for a, b in combinations(bearing, 2) if pr[a.id] != pr[b.id]
                 and (a.id not in indirect or b.id not in indirect)]
        bearing = direct_h
        avail, why = True, ""
        if "vibration" in d.required_sensors and not has_vib:
            avail, why = False, "needs a contact pickup or accelerometer"
        if "acoustic" in d.required_sensors and not has_ac:
            avail, why = False, "needs a microphone"
        score = (2 * len(pairs) + len(bearing)) / d.difficulty
        if not bearing or score <= 0:
            return
        if (pid, tuple(sorted(params.items()))) in done:
            score *= 0.3
            reason_extra += " Already run once; repeating it checks a conflicting result."
        sep = "; ".join(f"'{a.statement}' vs '{b.statement}'" for a, b in pairs[:2])
        direct = "; ".join(h.statement for h in bearing[:2])
        reason = (f"Separates {sep}. " if pairs else "") + (f"Directly tests: {direct}." if bearing else "") + reason_extra
        title = procedures.fill(d.title, params)
        out.append((score if avail else score / 100, NextTest(
            procedure_id=pid, title=title, params=params, reason=reason.strip(), discriminates=[h.id for h in bearing],
            pairs_separated=len(pairs), difficulty=d.difficulty, available=avail, unavailable_reason=why)))

    if not inp.captures:
        d = procedures.get("baseline")
        return [NextTest(procedure_id="baseline", title=d.title, reason="Start here: a baseline recording of the problem is "
                         "needed before any comparison is possible.", difficulty=1, available=True, pairs_separated=0)]

    # equipment on/off tests
    for eid, e in eq.items():
        preds: dict[str, str | None] = {}
        indirect = set()
        for h in open_h:
            if h.category is HypothesisCategory.SOURCE:
                preds[h.id] = "drop" if h.subject == eid else "no_drop"
                if h.subject != eid:
                    indirect.add(h.id)
            elif h.category is HypothesisCategory.ADDITIONAL_SOURCE and f"equipment_state:{eid}" in h.missing_tests:
                preds[h.id] = "drop"
            elif h.category is HypothesisCategory.RECORDING_CHAIN:
                preds[h.id] = "no_drop"
                indirect.add(h.id)
            elif h.category is HypothesisCategory.ELECTRICAL_HUM and e.kind in ELECTRIC_KINDS:
                preds[h.id] = "drop"
            elif h.category is HypothesisCategory.RATTLE and h.subject in (eid, e.name):
                preds[h.id] = "drop"
        add("equipment_state", {"target": eid}, preds, indirect=indirect)
    # recording chain vs acoustic hum
    preds = {}
    for h in open_h:
        if h.category is HypothesisCategory.RECORDING_CHAIN:
            preds[h.id] = "persists"
        elif h.category in (HypothesisCategory.ELECTRICAL_HUM,):
            preds[h.id] = "absent"
    add("electrical_hum", {}, preds)
    # aliasing
    add("alias_check", {}, {h.id: ("moves" if h.id == "H-ART-alias" else None) for h in open_h})
    # airborne control
    add("airborne_control", {}, {h.id: ("contact_higher" if h.category is HypothesisCategory.STRUCTURAL_PATH else
                                        "similar" if h.category is HypothesisCategory.AIRBORNE_PATH else None) for h in open_h})
    # isolation / mounting change per supported source
    for eid in eq:
        p = {h.id: ("drop" if (h.category is HypothesisCategory.STRUCTURAL_PATH and h.subject == eid) else
                    "no_drop" if (h.category is HypothesisCategory.AIRBORNE_PATH and h.subject == eid) else None) for h in open_h}
        add("isolation_comparison", {"target": eid}, p)
    # resonance: tap test & damping
    for h in open_h:
        if h.category is HypothesisCategory.RESONANCE:
            obj = h.subject if not h.subject.startswith("a structure") else (case.problem.receiver or "")
            if not h.missing_tests or "resonance_investigation:" in h.missing_tests:
                if obj:
                    add("resonance_investigation", {"object": obj}, {h.id: "rings_at_f"})
            if obj:
                add("damping_comparison", {"object": obj}, {h.id: "drop"})
    # location survey separates candidate sources by position
    src_open = [h for h in open_h if h.category is HypothesisCategory.SOURCE]
    if len(src_open) >= 2:
        add("source_location_survey", {}, {h.id: f"max_near_{h.subject}" for h in src_open},
            " Note: at low frequency, room modes can mislead a location survey.")
    if has_vib:
        add("contact_survey", {}, {h.id: f"max_at_{h.subject}" for h in open_h
                                   if h.category in (HypothesisCategory.STRUCTURAL_PATH, HypothesisCategory.RESONANCE)})
    # speaker buzz
    speakers = [e for e in eq.values() if e.kind == "speaker"]
    for spk in speakers:
        p = {h.id: "events" for h in open_h if h.category is HypothesisCategory.RATTLE}
        if p:
            add("speaker_buzz", {"target": spk.id}, p)
    out.sort(key=lambda t: -t[0])
    res = [t for _, t in out[:limit]]
    leading = [h for h in hyps if SUPPORT_ORDER[h.level] >= 3]
    if conclusion == "leading_explanation" and leading:
        d = procedures.get("fix_verification")
        res.append(NextTest(procedure_id="fix_verification", title=d.title, difficulty=1, available=True, pairs_separated=0,
                            reason=f"A leading explanation exists ({leading[0].statement}). After applying a remedy, verify it "
                                   "with repeated before/after measurements."))
    if not res:
        d = procedures.get("baseline")
        res.append(NextTest(procedure_id="baseline", title=d.title, difficulty=1, available=True, pairs_separated=0,
                            reason="No available test separates the remaining explanations. Add candidate equipment to the case "
                                   "or add a sensor (contact pickup) to unlock more tests."))
    return res

# 09 Diagnostic reasoning

Code: `src/sonicclue/diagnostics/engine.py` (RULESET_VERSION 1.0.0), `next_tests.py`. Tests: `tests/test_diagnostics_adversarial.py`, `tests/test_workflows.py::test_demo_*`.

## 1 Design (DEC-011)

Deterministic, versioned rules over typed evidence produce competing hypotheses with **ordinal** support: strongly_supported > supported > undetermined > weakened > contradicted. There are no probabilities or percentages, because no validated probabilistic model exists. ML and Bayesian models are gated on a labelled real-world dataset with held-out evaluation (spec 17 section 6). Same inputs give the same snapshot (tested). Every hypothesis lists its supporting and contradicting evidence ids, missing tests, rule ids with revisions, and plain-language explanation lines from fixed templates.

## 2 Evidence (CON-012)

| Kind | Produced from | Class |
|---|---|---|
| TONE | analysis peaks with prominence ≥ 15 dB, clustered across captures | measured |
| HARMONIC_FAMILY / MAINS_HARMONICS | analysis families | calculated |
| TRANSIENTS | ≥ 3 events, periodic or ≥ 6/min, ≥ 10 dB excess; sweep-locked buzz events | measured |
| RESONANCE | peaks with valid Q ≥ 5 (operating) or tap-test rings (procedure) | calculated / measured |
| STRUCTURAL_COHERENCE | eligible mic↔vibration cross results with γ² above threshold | calculated |
| STATE_EFFECT / NO_STATE_EFFECT | comparable state comparisons with exactly one equipment changed (overall and per tone) | calculated |
| RESIDUAL_AFTER_OFF | tone reduced but still present with the source off | inferred |
| INTERVENTION_EFFECT | comparable intervention comparisons with an unconfounded change description | calculated |
| CONFOUNDED_INTERVENTION | intervention changing source and path, undescribed, or with other equipment changes | inferred |
| NOT_COMPARABLE | comparisons failing comparability, or with several equipment changes | calculated (valid = false) |
| MEASUREMENT_QUALITY | invalid capture flags; ABA instability | measured / calculated |
| AIRBORNE_CONTROL | airborne-control procedure (mounted vs decoupled pickup) | measured |
| CHAIN_NOISE_TEST | electrical-hum procedure (connected vs terminated input) | measured |
| ALIAS_TEST | alias-check procedure (48 vs 44.1 kHz) | measured |
| POSITION_GRADIENT | survey procedures (≥ 6 dB spread) | measured |
| USER_OBSERVATION | case problem description | user_asserted |

## 3 Rules

| Rule | Hypothesis | Evidence used | Assumptions | Confounders | Supported when | Contradicted / weakened when | Abstains when | Next discriminating test |
|---|---|---|---|---|---|---|---|---|
| R-SRC-001@1 | equipment X is an excitation source | STATE_EFFECT / NO_STATE_EFFECT for X | only X changed; background stable | other equipment cycling; shared power; drift | ≥ 1 run with an effect → supported; ≥ 2 runs, or 1 run with measured repeatability and a passed ABA check → strong | runs where no channel shows an effect (u ≤ 3 dB) → contradicted; mixed → weakened | no comparable on/off run (spectral similarity alone never counts, ADV-002) | equipment_state(X) |
| R-ADD-001@1 | another source contributes at f | RESIDUAL_AFTER_OFF | tone detection reliable | partial shut-down of X | residual exists → supported | — | — | equipment_state(other equipment) |
| R-PATH-001@1 | vibration from X travels through structure | AIRBORNE_CONTROL and isolation INTERVENTION_EFFECT at frequencies linked to X; coherence (consistent only) | contact pickup mounted consistently | airborne excitation of the pickup (ADV-003); isolation also moving X | 1 decisive test → supported, 2 → strong | airborne control "airborne" or isolation without effect → weakened | only coherence exists (stays undetermined) | airborne_control, isolation_comparison(X) |
| R-PATH-002@1 | sound from X travels mainly through air | elimination | X is a supported source | | structural path weakened and source supported → supported | | otherwise undetermined | isolation_comparison(X) |
| R-RES-001@1 | object resonates near f | RESONANCE (operating Q), tap test matching a problem tone, damping intervention | | mount resonance of the sensor; damping also blocking airborne sound | tap match or damping reduction → supported; both → strong | damping without effect at f → weakened | peak alone (undetermined) | resonance_investigation(object), damping_comparison(object) |
| R-RAT-001@1 | intermittent impacts (rattle/buzz) | TRANSIENTS | | footsteps, handling noise | periodic events or sweep-locked events → supported | | irregular events only → undetermined | speaker_buzz(speaker) |
| R-CHN-001@1 | hum generated in the recording chain | CHAIN_NOISE_TEST, MAINS_HARMONICS | gain unchanged when terminating | ground loop changes when unplugging | persists without mic → supported | absent without mic → contradicted | not tested → undetermined | electrical_hum |
| R-HUM-001@1 | mains-powered equipment radiates hum | MAINS_HARMONICS, CHAIN_NOISE_TEST, STATE_EFFECT at mains harmonics | | | absent without mic AND an on/off effect at mains harmonics → supported | persists without mic → weakened | otherwise undetermined | electrical_hum, equipment_state(power equipment) |
| R-ART-001@1 | measurement problems explain part of the observation | MEASUREMENT_QUALITY | | | any invalid flag → supported (and the conclusion lists it) | | | repeat baseline with corrected settings |
| R-ART-002@1 | tones are aliases | ALIAS_TEST, ALIAS_RISK flags | source unchanged between rates | | tone moves with rate → supported | tone stays → contradicted | risk only → undetermined | alias_check |

Frequency linkage: frequency-specific evidence (airborne control, coherence) applies to equipment X only at frequencies where switching X off changed the signal. Fan-tone evidence never transfers to a broadband source (tested in the demo).

## 4 Conclusion and abstention

* `inconclusive`: no captures or analyses; or no primary hypothesis (source, additional source, hum, chain, rattle, alias) at ≥ supported. Reasons are listed, including "comparisons not comparable" and measurement problems.
* `leading_explanation`: exactly one primary hypothesis at ≥ supported (path and resonance hypotheses are mechanism details, not competitors).
* `multiple_explanations`: several primary hypotheses at ≥ supported. The text states they may act together (ADV-001).
Measurement problems (H-ART-quality) are always listed as an abstention reason when present.

## 5 Comparability rules (ADV-004/005/008)

See `src/sonicclue/compare/comparability.py` (table in its docstring): different sensor, position/location/distance > 10%, mounting, orientation, uncalibrated gain change, AGC on/unknown, processing change, invalid quality, simulated vs physical, or an intervention that changes the measurement setup → **invalidates**. Different device, sample rate or calibration profile, or unrecorded position/gain → **caveat**. Within a run, the gate `comparable_to_first` rejects non-comparable captures at recording time.

## 6 Measurement uncertainty vs evidence strength

Uncertainty (u95 in dB, repeatability type) belongs to the comparison. Evidence strength is the rule outcome. A tiny but resolvable change does not count (1 dB minimum effect). A large u95 (> 3 dB) prevents a "no effect" result from contradicting anything.

## 7 Next-test selection

For each candidate (procedure + parameters), each open hypothesis (not strong, not contradicted) gets a predicted outcome or None. Score = (2·pairs separated + directly tested hypotheses) / difficulty. Pairs only count if at least one member is directly tested; "no drop" predictions for other sources are indirect. Tests already completed with the same parameters are down-weighted ×0.3 and labelled as a repeat check. Unavailable tests (missing vibration sensor or microphone) are listed with the reason. A baseline is recommended first when there are no captures; fix verification is appended when a leading explanation exists. Tests that separate nothing are not recommended. Every recommendation's text explains which hypotheses it separates.

Test actions, prerequisites and expected patterns are defined in the procedure library (spec 10: preconditions, required sensors, difficulty 1-3, safety, confounds). Retry behaviour: failed gates repeat the step. Tests that cannot resolve ambiguity are excluded.

## 8 Adversarial cases (all automated, all passing)

| ID | Case | Required behaviour | Test |
|---|---|---|---|
| ADV-001 | two sources together | additional-source hypothesis; conclusion not a single attribution | `test_adv001_two_sources_residual_*` |
| ADV-002 | shared tone without shared path | spectral match alone never supports a source/path | `test_baseline_alone_is_inconclusive_*` |
| ADV-003 | airborne excitation of contact sensor | coherence alone keeps the structural path undetermined | `test_adv003_*` |
| ADV-004 | changed sensor mount | comparison invalid; source undetermined | `test_adv004_*` |
| ADV-005 | AGC unknown/on | level comparison invalid | `test_adv005_*` |
| ADV-006 | aliasing | alias test detects a moving tone | `test_adv006_alias_check_moves_tone` |
| ADV-007 | fix changes source and path | confounded; no path support | `test_adv007_*` |
| ADV-008 | quieter due to mic position | comparison invalid; no intervention effect | `test_adv008_*` |
| ADV-009 | high coherence from inadequate averaging | cross-channel ineligible; threshold 1 at n = 1 | `test_adv009_*` (pipeline + DSP) |
| ADV-010 | correct total, wrong attribution | no contribution shares, no percentages; explanation says shares are not estimated | `test_adv001_*` assertions |

Additional counterexample tests: ABA instability invalidates run evidence; clipped capture → measurement-artifact hypothesis; chain test in both directions; snapshot determinism.

## 9 Limitations

Rules and thresholds are engineering defaults validated on synthetic scenarios only (VALIDATION_REQUIRED, RQ-1). Real-world accuracy has not been measured. The engine does not model room acoustics (modes can mislead location surveys; this is stated in the recommendation text). No hypothesis can be stronger than its comparability and repeatability.

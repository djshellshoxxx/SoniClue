# 10 Guided diagnostic procedures

Definitions: `src/sonicclue/procedures/definitions/procedures.json` (validated as ProcedureDef, CON-010). Executor: `src/sonicclue/procedures/__init__.py`. App integration: `SonicClueApp.start_procedure / step_capture_spec / evaluate_gates / record_step_capture / procedure_action / _procedure_complete`. GUI: Guided tests screen. CLI: `procedure list|start|step|pause|resume|cancel`. Tests: `tests/test_workflows.py`, `tests/test_gui.py`.

## 1 Library (revision 1 each)

| Procedure | Purpose | Tier/sensors | Params | Steps (repeats) | Analysis → evidence |
|---|---|---|---|---|---|
| baseline | reference recording | 1 / any | – | prepare; baseline 20 s ×2 | baseline (tones, quality) |
| equipment_state | on/off/on (ABA) for one item | 1 / any | target | on 15 s ×2; switch off; off ×2; switch on; on ×1 | state comparison + ABA stability comparison → STATE_EFFECT / NO_STATE_EFFECT / RESIDUAL |
| source_location_survey | loudest position among candidates | 1 / acoustic | – | P1, P2, P3 10 s | POSITION_GRADIENT |
| receiver_position_survey | spread at receiver positions | 1 / acoustic | – | R1, R2, R3 | POSITION_GRADIENT |
| contact_survey | strongest vibration point | 2 / vibration | – | C1, C2, C3 | POSITION_GRADIENT (vibration) |
| vibration_survey | accelerometer along path | 3 / vibration | – | V1, V2, V3 | POSITION_GRADIENT (vibration) |
| speaker_buzz | buzz/rattle during a slow sweep | 1 / acoustic | target (speaker) | prepare; sweep 20 s with stimulus (-18 dBFS) | TRANSIENTS with sweep frequencies |
| resonance_investigation | tap test | 1 / any | object | tap 15 s | RESONANCE (tap, match to problem tones) |
| isolation_comparison | structural path via isolation | 1 / any | target | before ×2; intervention; after ×2 | INTERVENTION_EFFECT (path) or CONFOUNDED |
| damping_comparison | resonance via damping | 1 / any | object | before ×2; intervention; after ×2 | INTERVENTION_EFFECT (damping) |
| mounting_change | structural path via support change | 1 / any | target | before ×2; intervention; after ×2 | INTERVENTION_EFFECT (path) |
| electrical_hum | chain vs acoustic hum | 1 / acoustic | – | normal; disconnect mic; terminated | CHAIN_NOISE_TEST |
| airborne_control | contact pickup structural vs airborne | 2 / vibration | – | mounted; decouple; decoupled (mounting = resting) | AIRBORNE_CONTROL |
| alias_check | alias detection | 1 / any | – | 48 kHz; 44.1 kHz | ALIAS_TEST |
| fix_verification | remedy verification | 1 / any | – | before ×3; intervention; after ×3 | INTERVENTION_EFFECT with measured repeatability |

Each definition carries `preconditions`, `confounds`, `safety`, `success`, `difficulty`, guided `instruction` text with `{target}`/`{object}` placeholders, and an `expert_note` where useful. Placeholder resolution is tested for every step.

## 2 Execution state machine (SM-003)

`running --pause--> paused --resume--> running`; `running --(last step done)--> completed`; `running|paused --cancel--> cancelled`; `running|paused --fail--> failed`. Terminal states reject all events (SC_STATE). Wrong event for the current step kind (e.g. acknowledging a capture step) raises SC_STATE. Every transition returns a new immutable ProcedureRun, which is persisted immediately. After a crash the run is reloaded in its last persisted state; the GUI resumes the active run on case open.

## 3 Capture steps and gates

`step_capture_spec` derives the capture from the user's base configuration: condition label, merged equipment state, `position_id` applied to channels of the procedure's sensor type, mounting override for vibration channels, sample-rate override, stimulus, procedure ids/revision, repeat index, and the recorded intervention for steps after the intervention step. Settling intervals run before recording (the GUI shows a countdown; on the simulator they are capped at 0.5 s).

Gates: `no_clipping` (no |x| ≥ 0.999 FS), `signal_present` (some channel AC RMS ≥ -140 dBFS), `comparable_to_first` (no invalidating comparability issue vs the run's first accepted capture), `sync_shared_clock` (≥ 2 channels). A capture that ended early also fails. Failed captures are stored (immutable) under `<step>__rejected`; the step repeats with an explanation ("clipping: reduce the interface gain and repeat").

Stimulus steps require the output to be armed beforehand (SC_OUTPUT_NOT_ARMED otherwise); arming is one-shot.

## 4 Completion analysis

On completion `_procedure_complete` creates the comparisons for state/intervention procedures (one per channel label, tagged with the run id) and the ABA stability comparison. Other procedures are evaluated directly by the diagnostic engine from the run's captures. The run outcome text summarises the result. If the analysis fails, the run stays completed with "analysis failed: ..." in the outcome (recoverable by re-running diagnosis).

## 5 Safety boundaries

Procedures never instruct opening equipment, bypassing interlocks or operating machinery outside normal use. Equipment switching is limited to listed candidate equipment that "can be switched off safely". Tap tests say "gently"; speaker tests cap level at -12 dBFS peak and start low.

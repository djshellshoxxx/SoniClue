# SoniClue: Specification-Authoring Prompt

| Field | Value |
|---|---|
| Document ID | SC-PROMPT-SPEC |
| Version | 1.0.0 |
| Date | 2026-10-12 |
| Project | SoniClue: Affordable Sound and Vibration Cause Assistant (Circuit Drift Labs) |
| Companion | `docs/prompts/implementation-handoff.md` (SC-PROMPT-IMPL) |
| Embedding check | `tools/check_prompt_embedding.py` |

> **How to use this document.** Give the whole document, unabridged, to the agent or session that writes the SoniClue specification package. Every section marked **[BINDING]** is an acceptance condition. A package that does not meet them is not implementation-ready, however complete it looks.

---

## 0. Context and inputs

### 0.1 Product

SoniClue helps a user find the cause of an unwanted sound or vibration using affordable audio interfaces and sensors. It captures synchronized multichannel measurements, analyzes them, guides the user through procedures that discriminate between candidate causes, ranks causes by evidence (and abstains when the evidence is insufficient), compares measurements before and after interventions, and produces reproducible reports.

The owner's engineering brief names these subsystems, and each must appear in the package: acquisition; sensor adapters; calibration; synchronization; signal processing; comparisons; diagnostic evidence and cause ranking; guided procedures; application services; persistence; reporting; GUI and CLI; sensor bridge and firmware protocol; output arming (stimulus output); standalone packaging (Windows and Linux where required).

### 0.2 Source precedence

1. Owner-supplied baseline specification and explicit owner instructions.
2. This prompt.
3. Verified external facts: official documentation, standards, datasheets. Cite them.
4. Author engineering judgment, recorded as SELECTED_DEFAULT with rationale.

### 0.3 Repository state when this prompt was written

`djshellshoxxx/SoniClue` contains only `README.md`. **No baseline product specification was found** in the repository or the session uploads. Your first action is to locate it. If you cannot, record `DEC-000 Baseline product specification` as **BLOCKED** (owner: project owner; exit criterion: baseline specification committed under `spec/baseline/`). Then continue authoring, but no product-scope requirement may be classified above SELECTED_DEFAULT unless it comes from the owner.

### 0.4 Carried-forward ground rules (from the owner brief)

- Domain contracts and numerical processing stay independent of the GUI, devices, storage and orchestration. Dependencies point inward: UI, CLI, device, storage and bridge adapters → application services → domain contracts and numerics.
- Original measurement data is never modified. Derived results retain processing parameters, software versions, calibration, timing context, quality flags and provenance.
- Coherence is not proof of causation. Contact pickups are not calibrated accelerometers. Nominally equal sample rates do not mean the streams are synchronized.
- Measurement uncertainty is kept separate from diagnostic evidence strength.
- Mocks cannot replace physical hardware qualification. Unexecuted physical tests are labeled unexecuted.
- Scope is never silently shrunk. Every scope change is recorded with its consequences.

---

## 1. Status vocabulary and identifiers [BINDING]

Every requirement, decision, contract default, threshold and compatibility claim carries exactly one status:

| Status | Meaning | May dependent work start? |
|---|---|---|
| `CONFIRMED` | Stated by the owner or baseline spec, or a verified external fact with a citation. | Yes |
| `SELECTED_DEFAULT` | Engineering choice by the author with a recorded rationale. The owner may override it. | Yes |
| `VALIDATION_REQUIRED` | Provisional choice that needs evidence (feasibility task, measurement, hardware test). | Yes, if the spec states exactly what changes if validation fails |
| `BLOCKED` | Cannot be decided without an external input. | **No** |

ID prefixes: `REQ-<AREA>-NNN`, `DEC-NNN`, `FEAT-NNN`, `CON-NNN` (contracts), `INV-NNN`, `EDGE-NNN`, `RES-NNN` (resources), `SM-NNN` (state machines), `DIAG-NNN`, `ADV-NNN`, `CTX-NNN`, `VAL-NNN`, `FIX-NNN` (fixtures), `RISK-NNN`, `MOD-NNN`, `DEP-NNN`, `TASK-NNN`. IDs are never reused. Retired items keep their ID with status `RETIRED` and a reason.

---

## 2. Required package layout [BINDING]

```
spec/
  00-overview.md                     scope, glossary, architecture and dependency direction
  baseline/                          owner-supplied baseline (verbatim, never edited)
  requirements/requirements.md       REQ entries with status and source
  requirements/coverage-matrix.csv   requirement coverage matrix
  decisions/decision-register.csv    decision register
  decisions/adr/NNNN-<slug>.md       one ADR per significant decision
  features/FEAT-NNN-<slug>.md        vertical feature specs
  features/feature-wiring-matrix.csv feature-wiring matrix
  contracts/conventions.md           cross-contract conventions (section 5.2)
  contracts/schemas/*.schema.json    JSON Schema 2020-12
  contracts/examples/valid/*.json
  contracts/examples/invalid/*.json  each paired with *.expected-error.json
  contracts/validate_examples.py     proves the examples behave as declared
  numerics/invariant-catalog.md
  numerics/edge-cases.md
  lifecycle/resources.md
  lifecycle/state-machines.md
  lifecycle/concurrency.md
  diagnostics/rules.md
  diagnostics/adversarial-cases.md
  reproducibility/context-record.md
  reproducibility/comparability-matrix.md
  install/install-upgrade.md
  install/compatibility-matrix.csv
  validation/validation-matrix.csv
  validation/fixtures.md
  validation/datasets.md
  docs-standards.md
  dependencies/justifications.md
  dependencies/dependency-license-inventory.csv
  risks/risk-blocker-register.csv
  modules/module-reuse-catalog.md
  backlog/backlog.csv
  READINESS.md                       readiness-gate results (section 13)
```

The CSV files are canonical because they can be checked by machine. Markdown renderings of them are optional.

**Package-format decision (SELECTED_DEFAULT):** JSON Schema draft 2020-12 for contracts, because maintained validators exist for every candidate implementation language and it supports `$id` versioning. CSV for matrices, because it diffs cleanly and is easy to check. Record this as an ADR.

---

## 3. Decision register [BINDING]

*(Developer-completeness requirement 1: resolve decisions before declaring a specification ready.)*

### 3.1 Columns of `decision-register.csv`

`id, topic, question, status, choice, rationale, alternatives_rejected, sources, owner, resolution_method, required_evidence, dependent_tasks, exit_criterion, revisit_trigger, adr`

For every decision that is not `CONFIRMED` or `SELECTED_DEFAULT` (that is, every unresolved decision: `VALIDATION_REQUIRED` or `BLOCKED`), the chain **Owner → resolution method → required evidence → dependent tasks → exit criterion** must be complete. An empty cell in that chain fails the readiness gate.

### 3.2 Mandatory decisions

The register must cover at least these. Each line lists the sub-questions that must be answered.

| ID | Topic | Must answer |
|---|---|---|
| DEC-000 | Baseline product specification | Location, version, owner sign-off |
| DEC-001 | Supported operating-system versions and CPU architectures | Exact Windows editions and builds; Linux distributions, glibc baseline, display server (X11/Wayland); x86-64 and/or ARM64; audio stack per OS (e.g. WASAPI, ASIO, ALSA, PipeWire, PulseAudio) |
| DEC-002 | Minimum and reference hardware | Minimum CPU, RAM, disk and display; the named reference machine used for every performance measurement |
| DEC-003 | Exact dependency versions and native build toolchain | Language and runtime version; pinned library versions with a lockfile; compilers and SDKs; build hosts; reproducible-build method |
| DEC-004 | Initial supported audio interfaces and sensors | Named models; channel counts; sample rates; bit depths; driver requirements; sensor types (e.g. measurement microphone with calibration file, contact pickup, bridged accelerometer); which are targeted for qualification and which are only expected to work |
| DEC-005 | Supported acquisition modes and channel counts | Free-run capture, triggered capture, stimulus–response (output arming), long-duration monitoring; maximum channels per device and in total; single- vs multi-device; synchronization method per mode |
| DEC-006 | File formats and schema versions | Raw capture container; manifest format; case store; portable archive format; schema versioning scheme |
| DEC-007 | Calibration formats and conventions | Sensitivity units (e.g. V/Pa, V/(m·s⁻²), dBFS reference); frequency-response correction file format; direction of correction; uncertainty representation; validity frequency and level range |
| DEC-008 | Numerical defaults and eligibility thresholds | Window; segment length; overlap; minimum number of averages; coherence threshold as a function of averages; SNR minimum; clipping threshold; drift tolerance; minimum capture duration |
| DEC-009 | Packaging, licensing and distribution | Installer and package types per OS; code signing; project license; dependency license compatibility; distribution and update channel |
| DEC-010 | Complete-release scope | Features and hardware required for a "complete release" versus a "software-complete, hardware-unqualified" release |

### 3.3 Rules

- **No interchangeable choices in an implementation-ready module spec.** If a module spec says "library A or library B", "format X or Y", or "TBD", it is not ready. Either select a default with a rationale, or mark the dependent work BLOCKED behind a bounded feasibility task. The task must state a single question, the candidates, the evaluation evidence, and an exit criterion that selects exactly one option.
- A spec is not ready while any decision it depends on is BLOCKED.
- A VALIDATION_REQUIRED dependency is acceptable only if the spec states the fallback, or names the work that will be redone, if validation fails.

---

## 4. Vertical feature paths and the feature-wiring matrix [BINDING]

*(Developer-completeness requirement 2: specify complete vertical feature paths.)*

### 4.1 Per-feature spec (`features/FEAT-NNN-<slug>.md`)

Each user-facing feature documents its complete path:

**User action → input validation → application command → domain operation → adapter or numerical processing → persisted result → UI state → report/export → automated acceptance test.**

Each stage names the concrete module, function or command, the data contract (CON ID) and the error it can raise.

Each feature also has a **state table** covering all of these states:

| State | Trigger | What the UI/CLI shows | What is persisted | User recovery action | Test ID |
|---|---|---|---|---|---|
| loading | | | | | |
| empty | | | | | |
| invalid | | | | | |
| cancelled | | | | | |
| partial-success | | | | | |
| failed | | | | | |
| recovered | | | | | |

If a state cannot occur for a feature, write "not reachable" and give the reason. Do not leave the row blank.

### 4.2 `feature-wiring-matrix.csv` columns

The feature-wiring matrix identifies, for each feature: the UI control or CLI command, application handler, backend operation, data contract, storage records, displayed result, export representation and integration test.

`feature_id, ui_control_or_cli_command, application_handler, backend_operation, data_contract, storage_records, displayed_result, export_representation, integration_test, status`

### 4.3 Minimum features to reconcile against the baseline

Create or open a case. Configure devices and channels. Assign sensors and calibration. Capture (including synchronized multichannel capture). Review capture quality. Analyze (levels, spectra, coherence, transfer functions, band levels). Compare before and after. Run a guided procedure. View evidence and hypotheses, including abstention. Arm and emit an output stimulus. Connect a sensor bridge. Generate a report. Export and import a portable archive. Change settings. Recover after a crash or interrupted capture. Add or drop features only by recording a scope decision.

### 4.4 Rules

- No visible control may be considered complete because its layout exists.
- No backend feature may be considered complete if the intended user cannot invoke or inspect it.
- Every row in the wiring matrix needs a named integration test that drives the real path from the UI or CLI entry point down to persistence.

---

## 5. Public contracts [BINDING]

*(Developer-completeness requirement 3: define exact public contracts.)*

### 5.1 Contracts that require schemas plus valid and invalid examples

Provide machine-readable schemas and representative valid and invalid examples for: cases and capture manifests; channel and sensor descriptors; calibration profiles; analysis configuration and results; clock mappings; quality flags; procedures and execution state; evidence and hypothesis results; reports and portable archives; sensor bridge messages.

| ID | Contract |
|---|---|
| CON-001 | Case |
| CON-002 | Capture manifest |
| CON-003 | Channel descriptor |
| CON-004 | Sensor descriptor |
| CON-005 | Calibration profile |
| CON-006 | Analysis configuration |
| CON-007 | Analysis result |
| CON-008 | Clock mapping |
| CON-009 | Quality flag |
| CON-010 | Procedure definition |
| CON-011 | Procedure execution state |
| CON-012 | Evidence item |
| CON-013 | Hypothesis result |
| CON-014 | Report |
| CON-015 | Portable archive manifest |
| CON-016 | Sensor bridge message (every message type) |

### 5.2 Each schema, plus `contracts/conventions.md`, must define

- **Required versus optional fields.**
- **Defaults and allowed ranges**, each with a status from section 1.
- **Units and coordinate systems.** Units appear in field names or in a mandatory `unit` field. Sensor axes and orientation follow a stated right-handed frame relative to a documented mounting reference.
- **Timestamp and sample-index semantics.** Sample indices are zero-based integers per stream. Ranges are half-open `[start, end)`. Wall-clock time is RFC 3339 UTC and records its clock source. Each monotonic clock domain has an identifier. A clock mapping states its model (e.g. offset plus drift in ppm, piecewise), validity interval, fit residual and the method used to derive it.
- **Null versus unavailable versus invalid.** Select one uniform representation and apply it everywhere. Recommended SELECTED_DEFAULT: JSON `null` is forbidden. A value that may be missing uses a tagged object `{ "status": "valid" | "unavailable" | "invalid", "value"?, "reason"? }`. "Unavailable" means not measured or not applicable. "Invalid" means measured but rejected, with a reason code.
- **Enum evolution.** Readers map an unknown enum value to `unknown` and preserve the raw string. Writers never emit values outside their schema version.
- **Unknown-field behavior.** Specify per object whether unknown fields are rejected, or ignored and preserved on round trip. Extension points are explicit and documented.
- **Backward and forward compatibility.** Every document carries `schema_version` (semantic versioning: a major change breaks compatibility). State the supported reader window (e.g. current and previous major) and specify a migration function for each major step.
- **Validation errors.** Structured as `{ code, path (JSON Pointer), message, severity }`, with a stable catalog of codes.
- **Maximum sizes and resource limits.** Maximum channels, capture duration and bytes, string lengths, array lengths, archive size, bridge message size and message rate.

### 5.3 Example discipline

- Every schema has at least one valid example and one invalid example per class of constraint (missing required field, out-of-range value, wrong unit, bad enum, oversize value).
- Every invalid example has a sibling `*.expected-error.json` that gives the expected error code and path.
- `validate_examples.py` must pass: every valid example validates, and every invalid example fails with exactly its expected error.
- Examples must validate against the proposed schemas.
- Examples must not imply fields or behavior that are absent from the contract.

---

## 6. Numerical invariants [BINDING]

*(Developer-completeness requirement 4: establish numerical invariants.)*

### 6.1 Catalog entry template (`numerics/invariant-catalog.md`)

`INV-ID | statement | formula and convention | units | reference (standard or text) | test signal (FIX-ID) | independent reference calculation | floating-point tolerance | physical uncertainty (separate) | intentionally failing counterexample | test ID`

### 6.2 Required invariants

Each must state its convention explicitly and have a test.

- **Unit conversions and dimensional consistency.** Every quantity carries a unit. Conversions round-trip. Dimensionally invalid operations are rejected.
- **RMS, peak, PSD and spectral-density normalization.** A sine of amplitude A has RMS A/√2. Parseval: the sum of PSD·Δf over all bins equals the signal variance within tolerance. The spectral-density units (e.g. Pa²/Hz) are stated.
- **One-sided spectrum treatment, including DC and Nyquist.** Bins other than DC are doubled. DC and (for even N) the Nyquist bin are not.
- **Window gain and equivalent noise bandwidth.** Coherent gain = Σw/N. ENBW = N·Σw²/(Σw)² bins. Amplitude spectra correct by coherent gain and density spectra by ENBW. Integrating the PSD around a tone recovers A²/2 for every supported window.
- **Cross-spectrum orientation and transfer-function phase sign.** Pin down the convention, e.g. G_xy = conj(X)·Y and H1 = G_xy / G_xx. Then y(t) = x(t − τ) must yield phase −2πfτ, and a test must prove the sign.
- **Calibration correction direction.** For example, physical value = recorded value ÷ sensitivity. State whether a frequency-response correction in dB is added or subtracted, and give a test where applying it in the wrong direction fails.
- **Resampling gain, delay and boundary behavior.** Passband gain is unity within a stated ripple. Group delay is compensated or reported. Edge samples are marked with the transient range.
- **Band integration.** Fractional-bin band edges are treated in a stated way. The sum of adjacent bands equals the integral over their union.
- **Sample ranges and timing provenance.** Every derived value records the source stream, the sample range `[start, end)` and the clock mapping it used.
- **Missing-data exclusions.** Segments that overlap gaps, dropouts or clipping are excluded or flagged under a stated rule, and the excluded count is reported.
- **Denominator handling and invalid-bin masks.** Bins where G_xx is near zero, or below the noise floor, are masked as invalid with a reason. A masked bin is never reported as a numeric ratio.

### 6.3 Required edge-case behavior (`numerics/edge-cases.md`)

Table columns: `EDGE-ID | input condition | required behavior (compute / flag / mask / reject) | quality flag | user-facing message | test ID`. It must cover:

silence; constant (DC-only) signals; short captures (shorter than one segment, or fewer than the minimum averages); extreme amplitudes (full scale and near the noise floor); clipping; NaN and infinity in input; nonuniform timestamps; missing blocks; clock resets; mismatched sample rates; insufficient averaging; frequencies outside the calibration bounds.

### 6.4 Tolerances

Floating-point tolerances (rtol and atol justified by dtype and algorithm) are specified separately from physical measurement uncertainty (calibration uncertainty, estimator variance, synchronization error). They are never merged into a single "tolerance" field.

---

## 7. Ownership and lifecycle [BINDING]

*(Developer-completeness requirement 5: define ownership and lifecycle explicitly.)*

### 7.1 Resource table (`lifecycle/resources.md`)

For each resource specify: who creates it → who owns it → who may access it → when ownership transfers → who closes it → what happens on failure.

`RES-ID | resource | created by | owned by | may be accessed by | ownership transfers when | closed by | behavior on failure`

Required resources: device handles; callback buffers; queues; worker threads and processes; analysis arrays; database transactions; capture files; temporary exports; UI subscriptions; firmware connections.

### 7.2 State-transition tables (`lifecycle/state-machines.md`)

Required machines: **acquisition, analysis jobs, procedures, output arming, exports, recovery.** Each table lists: state, event, guard, action, next state, persisted effect. Each also states:

- the behavior for every invalid event in every state (reject with error code, or ignore idempotently);
- double-start and double-stop behavior;
- timeouts, and what happens when one expires.

**Output-arming safety is mandatory.** Emitting output requires an explicit arm step, an enforced level limit, a confirmation step and an automatic disarm timeout. On any fault, the output fails to a muted safe state.

### 7.3 Concurrency (`lifecycle/concurrency.md`)

- Lock ordering, wherever locks are used.
- Bounded backpressure. Every queue has a stated capacity and overflow policy. A real-time audio callback never blocks or allocates. If an overflow drops data, the dropped data becomes a recorded gap with a sample range and a quality flag. It is never silently lost.
- Cancellation points for every long operation.
- Shutdown order: stop producers, drain or discard by policy, finalize files, commit or roll back transactions, release devices.
- Timeouts for device open, bridge handshake, job execution and export.

---

## 8. Causal claims and counterexamples [BINDING]

*(Developer-completeness requirement 6: validate causal claims with explicit counterexamples.)*

### 8.1 Rule template (`diagnostics/rules.md`)

For every diagnostic rule `DIAG-NNN`, specify:

- Evidence it uses (CON-012 fields).
- Assumptions.
- Confounders.
- Counterexamples.
- What would contradict it.
- When it must abstain.
- The next discriminating test (a procedure ID).
- The fixture and test that prove it abstains or flags correctly.

### 8.2 Adversarial cases (`diagnostics/adversarial-cases.md`)

Each case needs a fixture, the required system behavior, and a test.

| ID | Case | Minimum required behavior |
|---|---|---|
| ADV-001 | Two sources operating together | Do not attribute the total to one source. Request an on/off isolation procedure. |
| ADV-002 | A shared tone without a shared transmission path | Frequency coincidence is not evidence of a path. Abstain unless an intervention or transfer test supports a path. |
| ADV-003 | Airborne excitation of a contact sensor | Do not claim a structure-borne path until an airborne control (e.g. a decoupled sensor or a reference microphone) rules out airborne pickup. |
| ADV-004 | A changed sensor mount | Mark the before/after comparison not comparable. |
| ADV-005 | Automatic gain changes | Detect AGC or require it to be disabled. Level comparisons are invalid while AGC is active or its state is unknown. |
| ADV-006 | Acquisition aliasing | State the anti-aliasing assumptions. Detect aliasing with a test that changes the sample rate. Flag tones whose apparent frequency moves. |
| ADV-007 | A fix that changes source output and transmission simultaneously | Report the improvement as confounded. Do not attribute it to the path or the source alone. |
| ADV-008 | A quieter recording caused by a changed microphone position | Treat the comparison as invalid unless the position is recorded as unchanged or a reference channel controls for it. |
| ADV-009 | High coherence from inadequate averaging | Enforce a minimum number of averages. The bias of the coherence estimate is about 1/n_avg, and a single segment always gives coherence 1. Below the eligibility threshold, abstain. |
| ADV-010 | A correct total response with incorrect source attribution | Validate attribution against per-source ground truth, not just the fit of the total. Abstain when attribution is not identifiable. |

### 8.3 Language rule

Report and UI text about causes comes from a closed set of templates keyed to evidence classes and rule outcomes. Do not substitute plausible language for validated evidence. Freeform "likely cause" text without rule support is forbidden.

---

## 9. Reproducible investigations [BINDING]

*(Developer-completeness requirement 7: design reproducible investigations.)*

### 9.1 Context record (`reproducibility/context-record.md`, carried in CON-002 and CON-007)

Record enough context to reproduce a measurement:

- equipment operating state;
- sensor identity and location;
- orientation and mounting;
- gain and processing settings;
- calibration and timing context;
- analysis parameters;
- procedure revision;
- intervention details;
- relevant environmental conditions, when available;
- software, firmware and hardware-profile versions.

### 9.2 Comparability matrix (`reproducibility/comparability-matrix.md`)

`context change | effect (invalidates / comparable with caveat / no effect) | detection method | user message | test ID`. This identifies which context changes invalidate a comparison.

### 9.3 Statement classes

Every report statement is tagged as exactly one of: **measured observation (`MEASURED`), calculated result (`CALCULATED`), inferred explanation (`INFERRED`), user assertion (`USER_ASSERTED`), unresolved question (`UNRESOLVED`).** The tag is a required field in CON-014 and is rendered visibly in reports.

---

## 10. Install, upgrade and compatibility [BINDING]

*(Developer-completeness requirement 8: include install, upgrade and compatibility contracts.)*

`install/install-upgrade.md` specifies:

- standard-user installation (no administrator rights required);
- offline dependency availability (everything bundled; no network needed at install or first run);
- device permissions (microphone privacy settings, udev or audio group membership, serial-port access for the bridge);
- required runtimes and drivers;
- first launch;
- upgrade and rollback;
- migration backups;
- side-by-side version behavior;
- uninstall behavior;
- recovery from interrupted installation;
- preservation of user cases and settings across all of the above.

Create a tested compatibility matrix. `install/compatibility-matrix.csv` columns: `os, os_version, arch, device, driver_or_runtime, build_id, tests_executed, result, date, status`, where `status` is one of `QUALIFIED | UNQUALIFIED | FAILED`. **An untested operating system or device must be labeled UNQUALIFIED, even if the software is expected to work.**

---

## 11. Independently reproducible validation [BINDING]

*(Developer-completeness requirement 9: make validation independently reproducible.)*

`validation/fixtures.md`, `validation/datasets.md` and `validation/validation-matrix.csv` define:

- **Analytic test signals.** Sines of known amplitude and frequency (both bin-centered and off-bin); white noise of known variance; pink noise; impulse; chirp; two-tone signals; delayed and filtered copies with a known delay and transfer function; clipped signals; signals with gaps; clocks drifting at a known ppm.
- **Deterministic fixture generators and seeds.** Every generator is versioned and seeded, and the seed is stored with the fixture.
- **Independent reference calculations.** Closed-form results, or a different implementation (e.g. direct DFT summation at extended precision for small N). Never the same library call the code under test makes.
- **Hardware test configurations.** Device, sensor, mounting, cabling, gain and the step-by-step procedure.
- **Ground-truth intervention records.** What was changed, by whom, and how it was verified.
- **Dataset permissions and redistribution rights** for every dataset.
- **Tuning versus held-out cases.** Held-out cases are frozen before any threshold is tuned and are never used for tuning.
- **Benchmark commands and environment.** The exact command, the reference machine (DEC-002) and the build ID.
- **Expected output and tolerances** for every validation item.
- **At least one intentionally failing case for every major validity gate.** That is an input the gate must reject, proving the gate can fail. Major gates: schema validation, calibration application, synchronization, spectral normalization, comparability, diagnostic abstention, install integrity.

`validation-matrix.csv` columns: `val_id, requirement_ids, gate, fixture_or_hw_config, reference_method, command, expected, tolerance, kind (software | hardware), must_fail_case, status (PASSED | FAILED | UNEXECUTED)`.

Tests must verify externally meaningful behavior rather than merely reproducing implementation logic.

---

## 12. Documentation, extensibility and dependencies [BINDING]

### 12.1 Developer documentation and comments (`docs-standards.md`)

*(Developer-completeness requirement 10.)*

Public API documentation must explain: **purpose, units, assumptions, ownership, side effects, errors, thread safety and examples.**

Code comments should explain:

- numerical conventions;
- physical assumptions;
- non-obvious constraints;
- concurrency decisions;
- compatibility workarounds;
- reasons for rejecting invalid measurements.

Avoid comments that merely restate code. Formulas and reference vectors link to the relevant spec section (INV-ID) and test.

### 12.2 Preventing premature extensibility (`dependencies/justifications.md`)

*(Developer-completeness requirement 11.)*

Each of the following requires a justification record: **new frameworks, new services, new abstractions, plugin systems, additional processes, and custom implementations of established numerical methods.** Record template: `item | concrete need (REQ IDs) | alternatives considered, including the standard library or no change | maintenance status | license | size and footprint | decision and rationale`. A custom numerical implementation must also be cross-checked against an established one in the validation matrix.

- Prefer cohesive reusable modules and narrow adapters.
- Do not build speculative frameworks for future features. Preserve extension points through documented contracts, and implement additional adapters when a concrete need exists.

`dependency-license-inventory.csv` columns: `dep_id, name, exact_version, purpose, license, license_compatible (yes/no/review), bundled (yes/no), source_url, justification_ref`.

---

## 13. Completion evidence and readiness [BINDING]

*(Developer-completeness requirement 12: define completion evidence and final reconciliation.)*

### 13.1 The final package must contain

| Required item | File |
|---|---|
| Requirement coverage matrix | `requirements/coverage-matrix.csv` (`req_id, status, spec_section, feature_ids, module_ids, contract_ids, test_ids, validation_ids`) |
| Feature-wiring matrix | `features/feature-wiring-matrix.csv` |
| Decision register | `decisions/decision-register.csv` |
| Numerical invariant catalog | `numerics/invariant-catalog.md` |
| Validation matrix | `validation/validation-matrix.csv` |
| Risk and blocker register | `risks/risk-blocker-register.csv` (`risk_id, description, kind (risk/blocker), likelihood, impact, owner, mitigation, dependent_tasks, exit_criterion, status`) |
| Module reuse catalog | `modules/module-reuse-catalog.md` (per module: public API, input/output types and units, dependencies, errors, lifecycle, thread safety, headless tests, integration example, portability limitations) |
| Dependency and license inventory | `dependencies/dependency-license-inventory.csv` |
| Development backlog with dependencies and acceptance criteria | `backlog/backlog.csv` (`task_id, title, req_ids, depends_on, owned_paths, acceptance_criteria, test_ids, blocked_by_decision, status`) |

### 13.2 Readiness gates (record their results in `READINESS.md`)

A module or feature spec is **implementation-ready** only when all of the following hold:

1. Every decision it depends on is CONFIRMED or SELECTED_DEFAULT, or VALIDATION_REQUIRED with a stated fallback. None are BLOCKED.
2. It contains no interchangeable alternatives and no "TBD".
3. Its complete vertical path and all seven states are specified (section 4).
4. Its contracts have schemas, and `validate_examples.py` passes.
5. Its numerical behavior is covered by INV and EDGE entries with tests.
6. Its resources and state machines are specified.
7. Any diagnostic rule it contains has counterexamples, abstention conditions and adversarial tests.
8. Each of its validation gates has at least one intentionally failing case.
9. Every new dependency and abstraction it introduces is justified.

### 13.3 Author self-audit (run before delivery)

- Search the package for `TBD`, `TODO`, "A or B" alternatives in module specs, and empty matrix cells. Resolve every hit or justify it.
- Run `contracts/validate_examples.py`. Record the output in `READINESS.md`.
- Check that every REQ appears in the coverage matrix, every FEAT appears in the wiring matrix, and every INV, EDGE, ADV and gate maps to a VAL.
- Check the specification for contradictions, incorrect mathematics, unsupported hardware assumptions, missing workflows and incomplete integration. Record what you found and how you resolved it.
- Do not hide unfinished work behind placeholders, mock results, disabled features presented as complete, or revised scope that was never recorded.

Completion cannot be inferred from a successful compilation, a passing unit-test suite, or an attractive interface alone.

### 13.4 Return format

Return:

1. the commit or PR containing the package;
2. the `READINESS.md` summary listing which specs are ready and which are blocked;
3. all BLOCKED and VALIDATION_REQUIRED decisions, each with its owner and exit criterion;
4. contradictions found in the baseline and how they were resolved;
5. scope changes recorded.

---

## Appendix A: Where each developer-completeness requirement is embedded

| Requirement | This prompt | Implementation handoff |
|---|---|---|
| 1. Resolve decisions before declaring a spec ready | §3, §13.2 | §3.1 |
| 2. Complete vertical feature paths | §4 | §3.2 |
| 3. Exact public contracts | §5 | §3.3 |
| 4. Numerical invariants | §6 | §3.4 |
| 5. Ownership and lifecycle | §7 | §3.5 |
| 6. Causal claims with counterexamples | §8 | §3.6 |
| 7. Reproducible investigations | §9 | §3.7 |
| 8. Install, upgrade and compatibility | §10 | §3.8 |
| 9. Independently reproducible validation | §11 | §3.9 |
| 10. Developer documentation and comments | §12.1 | §3.10 |
| 11. Preventing premature extensibility | §12.2 | §3.11 |
| 12. Completion evidence and final reconciliation | §13 | §3.12, §6 |

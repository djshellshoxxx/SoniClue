# SoniClue: Implementation Handoff

| Field | Value |
|---|---|
| Document ID | SC-PROMPT-IMPL |
| Version | 1.0.0 |
| Date | 2026-10-12 |
| Project | SoniClue: Affordable Sound and Vibration Cause Assistant (Circuit Drift Labs) |
| Depends on | Specification package produced under `docs/prompts/specification-authoring-prompt.md` (SC-PROMPT-SPEC) |
| Embedding check | `tools/check_prompt_embedding.py` |

> **How to use this document.** Give it, unabridged, to every implementation session or agent, together with the task assignment (section 2). The rules in section 3 are binding. Deviations require a recorded decision (ADR plus a decision-register entry), never a silent change.

---

## 1. Preconditions

1. The specification package exists under `spec/` and `spec/READINESS.md` lists which module and feature specs passed the readiness gates (SC-PROMPT-SPEC §13.2).
2. **Implement only specs marked ready.** Work that depends on a BLOCKED decision does not start. Record it in `risks/risk-blocker-register.csv`, continue with independent work, and return to it when the blocker clears.
3. Environment facts verified on 2026-10-12:
   - The repository is `djshellshoxxx/SoniClue` with default branch `main`.
   - Read access works through `git clone/fetch/pull` (public repo) and the GitHub API.
   - Write, branch, PR and merge operations work through the GitHub API, authenticated as `djshellshoxxx`.
   - **`git push` from the CLI has no credentials** ("No anonymous write access"). Either push commits through the API or configure a token before relying on CLI pushes.
   - Branch names start with `claude/`.

---

## 2. Task assignment format (coordinator → implementer)

Every assignment states:

- objective and deliverable;
- requirement IDs;
- spec references (FEAT, CON, INV, SM, DIAG, VAL IDs);
- owned files and modules (exclusive);
- permitted interface changes (default: none; changes to shared contracts go through the coordinator first);
- dependencies (TASK and DEC IDs);
- acceptance tests (VAL and test IDs that must pass);
- return format (section 5);
- integration plan (target branch, merge order, tests to rerun after merge).

There is one active owner per task. Shared schemas, migrations and the firmware protocol each have a single owner.

---

## 3. Binding implementation rules

### 3.1 Decisions (requirement 1)

- Implement exactly the choices in `decisions/decision-register.csv`. **Do not reintroduce interchangeable technology choices.** If an implementation reveals that a SELECTED_DEFAULT is wrong, stop the affected work, write an ADR proposing the change, and update the register (status, rationale, dependent tasks) before continuing.
- VALIDATION_REQUIRED decisions are resolved by running their stated resolution method and producing the required evidence. Record the evidence and update the status. Do not mark one resolved because the code compiles.
- For every decision that remains unresolved, keep the chain **Owner → resolution method → required evidence → dependent tasks → exit criterion** current.
- The covered topics are: supported operating-system versions and CPU architectures; minimum and reference hardware; exact dependency versions and native build toolchain; initial supported audio interfaces and sensors; supported acquisition modes and channel counts; file formats and schema versions; calibration formats and conventions; numerical defaults and eligibility thresholds; packaging, licensing and distribution; complete-release scope. Statuses are limited to CONFIRMED, SELECTED_DEFAULT, VALIDATION_REQUIRED and BLOCKED.

### 3.2 Vertical feature paths (requirement 2)

- Build each feature as a thin end-to-end slice: **User action → input validation → application command → domain operation → adapter or numerical processing → persisted result → UI state → report/export → automated acceptance test.**
- Implement the **loading, empty, invalid, cancelled, partial-success, failed and recovered** states alongside the normal path, as specified in the feature's state table.
- Keep `features/feature-wiring-matrix.csv` current: UI control or CLI command, application handler, backend operation, data contract, storage records, displayed result, export representation, integration test, status.
- **No visible control may be considered complete because its layout exists. No backend feature may be considered complete if the intended user cannot invoke or inspect it.** Do not leave controls unwired, results as placeholders, or mock behavior presented as production functionality.

### 3.3 Public contracts (requirement 3)

- The JSON Schemas in `spec/contracts/schemas/` are the source of truth for the case, capture manifest, channel and sensor descriptors, calibration profile, analysis configuration and results, clock mappings, quality flags, procedures and execution state, evidence and hypothesis results, reports and portable archives, and sensor bridge messages.
- Validate at every system boundary (file load, import, bridge receive, CLI and UI input). Implement exactly what the contract defines: required versus optional fields, defaults and allowed ranges, units and coordinate systems, timestamp and sample-index semantics, null versus unavailable versus invalid values, enum evolution, unknown-field behavior, backward and forward compatibility, structured validation errors, and maximum sizes and resource limits.
- CI runs `spec/contracts/validate_examples.py`, plus round-trip tests (load → save → load, preserving unknown fields where the contract says to). Examples must validate against the schemas. A contract change requires a schema version bump, migration code and new examples, coordinated with the contract owner before dependent implementation starts.

### 3.4 Numerical invariants (requirement 4)

- Every INV in `numerics/invariant-catalog.md` has an automated test that uses its stated fixture and an **independent reference calculation**. Covered invariants: unit conversions and dimensional consistency; RMS, peak, PSD and spectral-density normalization; one-sided spectrum treatment, including DC and Nyquist; window gain and equivalent noise bandwidth; cross-spectrum orientation and transfer-function phase sign; calibration correction direction; resampling gain, delay and boundary behavior; band integration; sample ranges and timing provenance; missing-data exclusions; denominator handling and invalid-bin masks.
- Every EDGE in `numerics/edge-cases.md` has a test of the specified behavior for: silence, constant signals, short captures, extreme amplitudes, clipping, NaN and infinity, nonuniform timestamps, missing blocks, clock resets, mismatched rates, insufficient averaging, and frequencies outside the calibration bounds.
- Floating-point tolerances stay separate from physical measurement uncertainty in both code and results. Never widen a tolerance to make a test pass without an ADR that explains why.

### 3.5 Ownership and lifecycle (requirement 5)

- Implement `lifecycle/resources.md` exactly for every resource: who creates it → who owns it → who may access it → when ownership transfers → who closes it → what happens on failure (columns: created by, owned by, may be accessed by, ownership transfers when, closed by, behavior on failure). Covered resources: device handles, callback buffers, queues, worker threads and processes, analysis arrays, database transactions, capture files, temporary exports, UI subscriptions and firmware connections.
- Implement the state machines for acquisition, analysis jobs, procedures, output arming, exports and recovery as explicit transition tables, with tests for every invalid transition and for double-start and double-stop behavior.
- Follow the documented lock ordering, bounded backpressure, cancellation points, shutdown order and timeouts. The audio callback never blocks or allocates. Overflow becomes a recorded gap with a quality flag. Output arming defaults to muted and auto-disarms.

### 3.6 Causal claims (requirement 6)

- Implement each DIAG rule with the evidence it uses, its assumptions, confounders, counterexamples, contradiction conditions, abstention conditions and next discriminating test.
- Every adversarial case has a passing test showing the system abstains, flags the problem or refuses the comparison as specified: two sources operating together; a shared tone without a shared transmission path; airborne excitation of a contact sensor; a changed sensor mount; automatic gain changes; acquisition aliasing; a fix that changes source output and transmission simultaneously; a quieter recording caused by a changed microphone position; high coherence from inadequate averaging; a correct total response with incorrect source attribution.
- Do not substitute plausible language for validated evidence. Cause text comes only from rule-backed templates. Coherence is never presented as proof of causation, and contact pickups are never presented as calibrated accelerometers.

### 3.7 Reproducibility (requirement 7)

- Persist the full context record with every capture and analysis: equipment operating state, sensor identity and location, orientation and mounting, gain and processing settings, calibration and timing context, analysis parameters, procedure revision, intervention details, relevant environmental conditions when available, and software, firmware and hardware-profile versions.
- Comparisons enforce `reproducibility/comparability-matrix.md`. Context changes that invalidate a comparison block it, with an explanation.
- Reports tag every statement as a measured observation, calculated result, inferred explanation, user assertion or unresolved question (`MEASURED`, `CALCULATED`, `INFERRED`, `USER_ASSERTED`, `UNRESOLVED`).
- Original measurement data is immutable. Derived data retains its parameters, versions, calibration, timing context, quality flags and provenance.

### 3.8 Install, upgrade and compatibility (requirement 8)

- Implement and test: standard-user installation; offline dependency availability; device permissions; required runtimes and drivers; first launch; upgrade and rollback; migration backups; side-by-side version behavior; uninstall behavior; recovery from interrupted installation; preservation of user cases and settings.
- Update `install/compatibility-matrix.csv` only from executed tests. **An untested operating system or device is labeled UNQUALIFIED, even if the software is expected to work.**

### 3.9 Validation (requirement 9)

- Use the specified analytic test signals, deterministic fixture generators and seeds, independent reference calculations, hardware test configurations, ground-truth intervention records, and datasets whose permissions and redistribution rights are recorded.
- Never tune thresholds on held-out cases.
- Run benchmarks with the recorded benchmark commands and environment on the reference machine, and compare against the expected output and tolerances.
- Keep at least one intentionally failing case for every major validity gate, running in CI.
- Tests must verify externally meaningful behavior rather than reproduce implementation logic. Mocks may isolate software layers. They never count as physical hardware qualification.

### 3.10 Documentation and comments (requirement 10)

- Every public API documents its purpose, units, assumptions, ownership, side effects, errors, thread safety and examples.
- Comments explain numerical conventions, physical assumptions, non-obvious constraints, concurrency decisions, compatibility workarounds, and reasons for rejecting invalid measurements. Avoid comments that merely restate code. Link formulas and reference vectors to their INV ID and test.

### 3.11 Extensibility and dependencies (requirement 11)

- New frameworks, new services, new abstractions, plugin systems, additional processes and custom implementations of established numerical methods each need an approved entry in `dependencies/justifications.md` **before** they are introduced.
- Prefer established, maintained libraries for standard capabilities, and cohesive reusable modules and narrow adapters. Do not build speculative frameworks for future features. Preserve extension points through documented contracts, and add adapters when a concrete need exists.
- Keep `dependencies/dependency-license-inventory.csv` exact: pinned version, license, compatibility and whether it is bundled.

### 3.12 Completion evidence (requirement 12)

- Keep current: the requirement coverage matrix, feature-wiring matrix, decision register, numerical invariant catalog, validation matrix, risk and blocker register, module reuse catalog, dependency and license inventory, and the development backlog with dependencies and acceptance criteria.
- **Completion cannot be inferred from a successful compilation, a passing unit-test suite, or an attractive interface alone.**
- **Do not hide unfinished work behind placeholders, mock results, disabled features presented as complete, or revised scope that was never recorded.**

---

## 4. Verification sequence (after the features are implemented)

1. Audit requirement and specification coverage (coverage matrix with no gaps).
2. Audit GUI/backend wiring and integration (every wiring-matrix row has a passing integration test).
3. Search for logic, numerical, lifetime, race, storage and import bugs.
4. Fix the findings and rerun the affected checks.
5. Audit security, privacy, dependencies and licensing.
6. Profile realistic workloads on the reference machine.
7. Optimize demonstrated bottlenecks while preserving correctness (rerun the INV and VAL tests).
8. Perform end-to-end and failure-path QA, covering every state in every feature state table.
9. Build clean standalone packages for each OS and architecture in scope (DEC-001, DEC-009).
10. Test installation and operation in a clean offline environment.
11. Reconcile branches, PRs and release documentation.

---

## 5. Implementer return format (per task)

- task ID, branch, PR, and head commit;
- changes made (files and modules) and the contracts affected;
- tests added and run, with results (commands included);
- validation items moved to PASSED, FAILED or UNEXECUTED;
- unresolved issues, new risks and blockers, and proposed decision changes.

---

## 6. Required final report (coordinator → owner)

The final report must state each of the following. "Not done" and "unexecuted" are acceptable answers. Omitting an item is not.

1. **What was implemented**, per FEAT and REQ, with links to the coverage matrix.
2. **What was actually tested**: commands, environments, build IDs and results.
3. **Which hardware was qualified**: the QUALIFIED rows of the compatibility matrix. Everything else is listed as UNQUALIFIED.
4. **Which acceptance criteria passed, failed or remain unexecuted**: a validation-matrix summary with counts, listed per item.
5. **Measured performance** on the reference machine against the targets.
6. **Known limitations.**
7. **Build and release identifiers**, checksums, and the dependency and license notices.
8. **Every branch and PR disposition**: merged, closed as superseded (with reason), or retained (with owner and blocker).
9. A clear separation of work that is implemented, tested, physically qualified, unexecuted and blocked.

Completion cannot be inferred from a successful compilation, a passing unit-test suite, or an attractive interface alone.

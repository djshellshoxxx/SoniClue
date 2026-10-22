# SonicClue: Continuation Record

Last updated: 2026-10-22.

## Current state

* Repository: `djshellshoxxx/SoniClue`; base `main` at `6d52f5a` when this work began. PR #12 (`claude/code-audit`) was merged into `main` as `9cbec5a` on 2026-10-22.
* Product: SonicClue 0.1.0, software-complete for the implemented scope and hardware-unqualified. This session adds app-service and CLI support for concurrent multi-device capture, resolves four independent DSP/diagnostics review findings, and reconciles user and specification documentation.
* Multi-device capture is exposed through `SonicClueApp.start_multi_capture` and `sonicclue-cli capture-multi`. Each device remains in its own clock domain; mappings are estimated against the first capture from shared-reference channels. Physical qualification HQ-05 remains pending.
* Analysis supports full-length captures up to `max_analysis_seconds` (default 14,400 s); spans over 600 s spool to disk.
* PR #12 is merged. CI run #45 passed Linux and Windows tests plus Linux and Windows standalone bundle build/smoke-test jobs.

## Verification completed locally

* Full pytest suite: reached 100% with no failure/error markers.
* Generated schemas: `python tools/gen_schemas.py --check` (94 contract files current).
* Contract examples: `python docs/specs/contracts/validate_examples.py` (47/47).
* Numerical vectors: `python tools/gen_test_vectors.py --check` (12/12).
* Prompt embedding: `python tools/check_prompt_embedding.py` (422/422).
* Focused tests: multi-device application persistence/alignment and startup rollback; adversarial A-B-A, invalid-quality and electrical-hum comparability cases; DSP measured-uncertainty floor; demo diagnosis and report workflow.
* Python compilation, CLI `capture-multi` help/parser, and `git diff --check` passed. Linux and Windows standalone bundle builds and clean-environment smoke tests passed in CI run #45.

## Completed software work in this session

* TASK-031: app-service multi-device capture startup, rollback, persistence, clock mapping, and `capture-multi` CLI.
* TASK-042: independent review of specs 08 and 09; four findings and their corrections are recorded in `docs/specs/24-specification-audit.md`.
* Corrected the source-evidence strength rule to count independent runs rather than evidence rows. Invalid measurement flags now surface as artifact evidence; electrical-hum chain tests verify capture quality and comparable recording conditions.
* Documented the 0.25 dB uncertainty floor for measured repeated comparisons with zero observed variance.

## Remaining external or manual work

| Item | Status / exit criterion |
|---|---|
| TASK-015 AppImage | Open; build and test on Ubuntu 22.04 and Fedora 40 clean VMs (depends on TASK-020). |
| TASK-020 clean-machine install | Open; offline install and HQ-09 on clean Windows 11 and Ubuntu VMs. |
| TASK-021 reference-machine performance | Open; owner designates reference machine and benchmarks/HQ-03 meet spec 16. |
| TASK-022..025 hardware qualification | Blocked on physical interfaces/sensors; run HQ-02/04/05/06. |
| TASK-026 sensor bridge | Blocked on board selection and firmware. |
| TASK-030 ASIO | Blocked on Steinberg licensing. |
| TASK-032 code signing | Blocked on signing certificate; CI artifacts remain unsigned. |
| TASK-033 project licence | Owner decision required; commit selected licence. |
| TASK-040 real-world diagnostic validation | Open; collect held-out real investigations and report accuracy/abstention. |
| TASK-041 ML diagnosis | Blocked on TASK-040 and owner decision. |
| TASK-043 accessibility | Open; manual NVDA/Orca walkthrough. |

The independent review covered specs 08 and 09; the broader product audit is still authored by the implementation session. Synthetic and simulated test results do not establish real-world diagnostic accuracy.

## Next actions

1. Continue the external/manual items above as their prerequisites become available; hardware, owner decisions, clean VMs, and real-world datasets are required for the remaining qualifications.

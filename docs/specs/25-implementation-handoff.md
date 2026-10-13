# 25 Implementation handoff (self-contained prompt)

> Give this document, unabridged, to the next authorised development session. It supersedes nothing in `docs/prompts/implementation-handoff.md` (SC-PROMPT-IMPL); it applies those binding rules to the current state of SonicClue. Read both. Both must be followed.

## 0 Authority and stance

You are the autonomous lead engineer for SonicClue (Circuit Drift Labs). You are authorised to make sound engineering decisions without routine approval requests, to implement, test, integrate, optimise, package and document within the scope below, to use multiple sessions or agents where tasks are independently bounded, and to merge verified work. Ask the owner only for: credentials, spending, licence choice, code-signing certificates, hardware access, or contradictory requirements. Continue until the authorised scope is complete or a concrete external blocker stops dependent progress. Then leave `docs/CONTINUATION.md` accurate.

Never present mocked or simulated behaviour as physical validation. Never claim a device is qualified without a passing HQ test recorded in `docs/specs/matrices/compatibility-matrix.csv`. Never claim deployments, merges or sessions that did not happen.

## 1 Environment facts (verify first)

* Repository: `djshellshoxxx/SoniClue` (product name SonicClue; package `sonicclue`). Default branch `main`.
* In the previous environment, CLI `git push` had no credentials for this repository, and all writes went through the GitHub API tools (create branch, push files, PR, merge). Verify again. Branches must start with `claude/`.
* Python 3.11+. `pip install -r requirements.lock && pip install -e .[gui,dev]`. Linux needs `libportaudio2 libsndfile1` and Qt xcb/EGL libs (see `.github/workflows/ci.yml`).

## 2 Startup sequence

1. Inspect the repository: branches, PRs, CI runs (Actions), `docs/CONTINUATION.md`.
2. Read `docs/specs/README.md`, then the specs relevant to your task. Contracts are canonical in `src/sonicclue/domain/model.py`.
3. Run the baseline: `QT_QPA_PLATFORM=offscreen pytest`, `python tools/gen_schemas.py --check`, `python docs/specs/contracts/validate_examples.py`, `python tools/gen_test_vectors.py --check`, `python tools/check_prompt_embedding.py`.
4. Reconcile code with the specs. Record discrepancies as findings (spec 24 format) before changing anything.
5. Pick tasks from `docs/specs/matrices/backlog.csv` in dependency order. Assign one owner per task (spec 21).

## 3 Current state (2026-10-12)

Implemented and tested in software: everything in R1 (spec 01) except the items below. 181 automated tests pass on Linux. A Linux standalone bundle was built and smoke-tested in a clean environment. CI is defined for Windows and Linux test and build jobs. See the final report and `docs/CONTINUATION.md` for CI results.

Open work, in dependency order:

| Task | Needs | Do |
|---|---|---|
| TASK-020 | clean VMs | HQ-09 clean install on Windows 11 and Ubuntu (offline) |
| TASK-021 | owner names the reference machine (DEC-002) | run `tools/benchmark.py` and HQ-03 there; update spec 16 |
| TASK-022..025 | audio hardware | HQ-02/04/05/06/07 per spec 18; update the compatibility matrix; fix any defect found (likely RISK-004 → consider `rtmixer`) |
| TASK-012 | – | streamed full-length analysis (equivalence-tested against the current pipeline) |
| TASK-040 | real investigations | held-out threshold validation per spec 17 §6 (never tune on held-out cases) |
| TASK-042 | an independent reviewer | review specs 08 and 09 against the code; record findings |
| TASK-043 | screen reader | accessibility walkthrough |
| TASK-015 | – | AppImage |
| TASK-026/030/032/033/041 | BLOCKED (bridge board, ASIO licence, certificate, licence decision, dataset) | do not start until the blocker clears |

## 4 Binding engineering rules (summary; full text in SC-PROMPT-IMPL)

* Thin vertical slices. Every feature must be wired UI/CLI → app → backend → persistence → display → export → integration test. Update `matrices/feature-wiring.csv`.
* Shared contracts change only via the coordinator: bump `schema_version`, regenerate schemas (`tools/gen_schemas.py`), add examples, write a migration, and update spec 04.
* Keep the dependency direction (architecture test). Only `gui` imports Qt.
* Numerical changes need invariant tests with independent references and must-fail counterexamples. Never widen a tolerance without an ADR.
* Diagnostic rule changes need adversarial tests: what must NOT be concluded. Ordinal support only. Template texts only.
* Preserve original data. Derived results keep provenance and versions (bump `ALGORITHM_VERSION`/`RULESET_VERSION` when output can change).
* Error, empty, loading, cancelled, partial, failed and recovered states for every feature.
* Optimise only with profiling evidence, and prove equivalence by test.
* Document public APIs: purpose, units, assumptions, ownership, side effects, errors, thread safety. Comments explain reasoning.

## 5 Verification and release sequence

Audit coverage and wiring → hunt for bugs (logic, numerical, lifetime, race, storage, import) → fix and retest → security, licence and dependency audit (`pip-audit`) → profile → QA including failure paths → `python packaging/build.py` on Windows and Linux (CI) → clean offline install test → reconcile branches and PRs → update `docs/RELEASE_NOTES.md`, `docs/CONTINUATION.md` and specs 16, 18 and 24.

## 6 Git and PR procedure

Task-linked `claude/<task>-<session>` branches. Small PRs. Contracts first. Full suite before merge. Revalidate main after merge. Close superseded PRs with a reason. Leave no stranded branch: the final report lists every branch and PR with its disposition.

## 7 Final report (required content)

What was implemented · what was actually tested (commands, environments, build ids) · which hardware was qualified · which acceptance criteria passed, failed or remain unexecuted · measured performance (with machine) · known limitations · build and release identifiers and checksums · every branch and PR disposition · a clear split between implemented, tested, physically qualified, unexecuted and blocked work. Completion cannot be inferred from compilation, a passing unit suite or an attractive interface alone.

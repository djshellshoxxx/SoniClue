# SonicClue Wiki

SonicClue is a local-first application for investigating unwanted sound and vibration. It helps users test competing explanations, keep measurements comparable, and document what the evidence does and does not support.

This guide supplements the repository’s [README](../../README.md), [User Guide](../USER_GUIDE.md), [Release Notes](../RELEASE_NOTES.md), and [specification index](../specs/README.md). The specifications and source code remain authoritative when implementation details change.

## Start here

- [User guide](../USER_GUIDE.md): the full user guide in `docs/USER_GUIDE.md` (install, sensors, running an investigation)
- [Developer overview](Developer-Overview.md): architecture, design decisions, data flow
- [Developer code map](Developer-Code-Map.md): where things live and where to change them
- [Developer build and test](Developer-Build-and-Test.md): setup, checks, CI, packaging
- [Developer conventions](Developer-Conventions.md): code rules, gotchas, known limits

Companion pages (kept from earlier revisions):

- [User guide (wiki)](User-Guide.md): install, set up sensors, run an investigation, understand results, and export a report.
- [Feature reference](Feature-Reference.md): what the major app features do and how they fit together.
- [Developer guide](Developer-Guide.md): earlier developer notes.
- [Architecture and data flow](Architecture-and-Data-Flow.md): follow a capture from an audio device to an evidence report.
- [Troubleshooting and limitations](Troubleshooting-and-Limitations.md): common problems, qualification status, and boundaries on conclusions.

## What SonicClue does

SonicClue guides controlled tests such as equipment on/off comparisons, location surveys, contact-sensor checks, isolation or damping changes, resonance taps, and before/after verification. It tracks the excitation source, transmission path, receiver, and measurement system as separate possibilities. Its deterministic, versioned rules show supporting and conflicting evidence, identify missing tests, and can return an inconclusive result.

The app is designed to work offline. It includes a desktop GUI, a CLI, a built-in simulator, case storage, analysis, comparisons, and HTML/PDF/JSON/CSV reporting.

## Evidence and interpretation

- A frequency match, correlation, or coherence result alone does not establish causation.
- Comparisons are only useful when sensor, position, mounting, orientation, gain, AGC, processing, and capture quality are sufficiently consistent.
- Diagnostic support is ordinal (for example, supported or weakened), not a probability.
- Reports distinguish measured, calculated, inferred, user-provided, and unresolved statements.
- Simulated examples are labelled **SIMULATED** and are not physical measurements.

## Project status

The repository describes SonicClue 0.1.0 as software-complete for its initial scope, with testing on synthetic and simulated data. It also states that no physical audio interface or sensor has been hardware-qualified. Check the [current compatibility matrix](../specs/matrices/compatibility-matrix.csv), [release notes](../RELEASE_NOTES.md), and repository Actions before relying on any particular build or device.

The product licence is still marked as undecided in [LICENSE-NOTICE.md](../../LICENSE-NOTICE.md).
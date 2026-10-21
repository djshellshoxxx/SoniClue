# Architecture and Data Flow

The detailed module contracts and enforced rules are in [System Architecture](../specs/03-system-architecture.md) and [Module Contracts](../specs/04-module-contracts.md). This page is a high-level map for contributors.

## Layers

SonicClue uses Python 3.11+, NumPy/SciPy for numerical work, PortAudio through `sounddevice` for acquisition, Pydantic contracts with generated JSON Schemas, SQLite and chunked files for cases, and PySide6/pyqtgraph for the GUI. The CLI and GUI call into shared application services.

The architecture separates:

- **Presentation:** `gui` and `cli`
- **Orchestration:** `app` services and background jobs
- **Capabilities:** acquisition, storage, procedures, diagnostics, comparisons, analysis, sensors, synchronization, reporting, stimulus, qualification
- **Foundations:** DSP and domain contracts

Only the GUI layer should depend on Qt. DSP/domain code is intended to remain importable without the GUI and device stack. Architecture checks enforce key dependency boundaries.

## Capture-to-report path

1. A capture session reads blocks from one input device. Its callback performs bounded work and passes samples through a bounded queue.
2. A writer thread drains the queue, accounts for gaps, and writes chunked audio plus a journal.
3. The case store records a validated capture manifest. Captures are retained as source evidence.
4. Analysis produces results tied to source capture IDs and algorithm versions.
5. Comparisons check whether conditions are comparable and calculate differences with uncertainty.
6. Guided procedures record run state and acceptance outcomes.
7. The diagnostic engine evaluates versioned rules and creates an evidence snapshot with supporting, conflicting, and missing evidence.
8. The report builder creates HTML, PDF, JSON, or CSV output with statement classes and provenance.

## Threading and lifecycle

The GUI thread handles widgets and small live updates. Audio callbacks must not block, perform storage I/O, or call into GUI objects. Capture writing and longer application jobs run outside the GUI thread. A playback watchdog can stop output at its deadline.

Stopping a capture finalizes and keeps data written so far; cancelling discards the capture according to the documented behavior. Interrupted captures can be recovered from journal data on the next open. Closing the app stops/disarms output before shutting down jobs and closing the case store.

## Data and trust boundaries

- Raw captures are retained without acquisition-time filtering, gain, limiting, compression, or dither.
- Derived records point back to source captures and versioned algorithms/rules.
- Gaps, clipping, invalid samples, and device failures are represented explicitly.
- Archives and imported files are treated as untrusted input and validated.
- Local-first operation requires no account, cloud service, or GPU.

For implementation details and lifecycle/error contracts, consult specs 04, 05, 13, and 15.
#!/usr/bin/env python3
"""Verify that every developer-completeness requirement is embedded in both
the specification-authoring prompt and the implementation handoff.

Each requirement maps to the key phrases from the owner's requirement text.
A phrase must appear (case-insensitive, whitespace-normalized) in BOTH
documents. Exit code 0 = all embedded, 1 = something is missing.

Usage: python3 tools/check_prompt_embedding.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = {
    "spec-prompt": ROOT / "docs/prompts/specification-authoring-prompt.md",
    "impl-handoff": ROOT / "docs/prompts/implementation-handoff.md",
}

REQUIREMENTS = {
    "1 decisions": [
        "operating-system versions and CPU architectures",
        "minimum and reference hardware",
        "exact dependency versions and native build toolchain",
        "initial supported audio interfaces and sensors",
        "acquisition modes and channel counts",
        "file formats and schema versions",
        "calibration formats and conventions",
        "numerical defaults and eligibility thresholds",
        "packaging, licensing",
        "complete-release scope",
        "CONFIRMED", "SELECTED_DEFAULT", "VALIDATION_REQUIRED", "BLOCKED",
        "Owner → resolution method → required evidence → dependent tasks → exit criterion",
        "interchangeable",
    ],
    "2 vertical paths": [
        "User action → input validation → application command → domain operation"
        " → adapter or numerical processing → persisted result → UI state"
        " → report/export → automated acceptance test",
        "loading", "empty", "invalid", "cancelled", "partial-success", "failed", "recovered",
        "UI control or CLI command", "application handler", "backend operation",
        "data contract", "storage records", "displayed result",
        "export representation", "integration test",
        "No visible control may be considered complete because its layout exists",
        "No backend feature may be considered complete if the intended user cannot invoke or inspect it",
    ],
    "3 contracts": [
        "capture manifest", "channel and sensor descriptors", "calibration profile",
        "analysis configuration", "clock mapping", "quality flag", "procedure",
        "execution state", "evidence", "hypothesis", "report", "portable archive",
        "sensor bridge message",
        "required versus optional", "defaults and allowed ranges",
        "units and coordinate systems", "timestamp and sample-index semantics",
        "null versus unavailable versus invalid", "enum evolution",
        "unknown-field behavior", "backward and forward compatibility",
        "validation errors", "maximum sizes and resource limits",
        "examples must", "validate against",
    ],
    "4 numerics": [
        "unit conversions and dimensional consistency",
        "RMS, peak", "PSD", "spectral-density normalization",
        "one-sided spectrum treatment, including DC and Nyquist",
        "window gain and equivalent noise bandwidth",
        "cross-spectrum orientation and transfer-function phase sign",
        "calibration correction direction",
        "resampling gain, delay", "boundary behavior", "band integration",
        "sample ranges and timing provenance", "missing-data exclusions",
        "denominator handling and invalid-bin masks",
        "silence", "constant", "short captures", "extreme amplitudes", "clipping",
        "NaN", "infinity", "nonuniform timestamps", "missing blocks", "clock resets",
        "mismatched", "insufficient averaging", "outside the calibration bounds",
        "floating-point tolerances", "physical measurement uncertainty",
    ],
    "5 lifecycle": [
        "who creates", "owned by", "who may access", "ownership transfers",
        "closes", "on failure",
        "device handles", "callback buffers", "queues", "worker threads",
        "analysis arrays", "database transactions", "capture files",
        "temporary exports", "UI subscriptions", "firmware connections",
        "acquisition", "analysis jobs", "procedures", "output arming", "exports", "recovery",
        "lock ordering", "bounded backpressure", "cancellation points",
        "shutdown order", "timeouts", "double-start", "double-stop",
    ],
    "6 causal claims": [
        "evidence it uses", "assumptions", "confounders", "counterexamples",
        "contradict", "abstain", "next discriminating test",
        "two sources operating together",
        "shared tone without a shared transmission path",
        "airborne excitation of a contact sensor", "changed sensor mount",
        "automatic gain changes", "acquisition aliasing",
        "changes source output and transmission simultaneously",
        "quieter recording caused by", "microphone position",
        "high coherence from inadequate averaging",
        "correct total response with incorrect source attribution",
        "Do not substitute plausible language for validated evidence",
    ],
    "7 reproducibility": [
        "equipment operating state", "sensor identity and location",
        "orientation and mounting", "gain and processing settings",
        "calibration and timing context", "analysis parameters",
        "procedure revision", "intervention details", "environmental conditions",
        "software, firmware", "hardware-profile versions",
        "invalidate a comparison",
        "measured observation", "calculated result", "inferred explanation",
        "user assertion", "unresolved question",
    ],
    "8 install": [
        "standard-user installation", "offline dependency availability",
        "device permissions", "runtimes and drivers", "first launch",
        "upgrade and rollback", "migration backups", "side-by-side version behavior",
        "uninstall behavior", "recovery from interrupted installation",
        "preservation of user cases and settings", "compatibility matrix",
        "labeled UNQUALIFIED, even if the software is expected to work",
    ],
    "9 validation": [
        "analytic test signals", "deterministic fixture generators and seeds",
        "independent reference calculations", "hardware test configurations",
        "ground-truth intervention records", "permissions and redistribution rights",
        "held-out", "benchmark commands", "environment",
        "expected output and tolerances",
        "intentionally failing case for every major validity gate",
        "externally meaningful behavior rather than",
    ],
    "10 documentation": [
        "purpose, units, assumptions, ownership, side effects, errors, thread safety",
        "examples", "numerical conventions", "physical assumptions",
        "non-obvious constraints", "concurrency decisions",
        "compatibility workarounds", "reasons for rejecting invalid measurements",
        "merely restate code",
    ],
    "11 extensibility": [
        "new frameworks", "new services", "new abstractions", "plugin systems",
        "additional processes",
        "custom implementations of established numerical methods",
        "cohesive reusable modules and narrow adapters",
        "speculative frameworks for future features",
        "extension points through documented contracts",
    ],
    "12 completion": [
        "requirement coverage matrix", "feature-wiring matrix", "decision register",
        "numerical invariant catalog", "validation matrix",
        "risk and blocker register", "module reuse catalog",
        "dependency and license inventory",
        "development backlog with dependencies and acceptance criteria",
        "Completion cannot be inferred from a successful compilation, a passing"
        " unit-test suite, or an attractive interface alone",
        "Do not hide unfinished work behind placeholders, mock results, disabled"
        " features presented as complete, or revised scope that was never recorded",
    ],
}

# Additional items only the handoff must carry (the required final report).
HANDOFF_ONLY = [
    "What was implemented", "What was actually tested",
    "Which hardware was qualified",
    "Which acceptance criteria passed, failed or remain unexecuted",
    "Measured performance", "Known limitations",
    "Build and release identifiers", "Every branch and PR disposition",
]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "")).lower()


def main() -> int:
    texts = {name: norm(p.read_text(encoding="utf-8")) for name, p in DOCS.items()}
    missing = []
    total = 0
    for req, phrases in REQUIREMENTS.items():
        for phrase in phrases:
            for name, text in texts.items():
                total += 1
                if norm(phrase) not in text:
                    missing.append(f"[{name}] req {req}: {phrase!r}")
    for phrase in HANDOFF_ONLY:
        total += 1
        if norm(phrase) not in texts["impl-handoff"]:
            missing.append(f"[impl-handoff] final report: {phrase!r}")
    for line in missing:
        print("MISSING", line)
    print(f"{total - len(missing)}/{total} checks passed")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())

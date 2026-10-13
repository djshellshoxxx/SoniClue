"""Domain-level error types.

Every error carries a stable machine-readable ``code`` (catalogued in
docs/specs/04-module-contracts.md section "Error catalogue") so that the CLI,
GUI and reports can render consistent messages and tests can assert on codes
rather than message text.
"""

from __future__ import annotations


class SonicClueError(Exception):
    """Base class. ``code`` is stable across releases; ``message`` is for humans."""

    code = "SC_ERROR"

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        if code:
            self.code = code
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code}] {self.message}"


class ValidationError(SonicClueError):
    code = "SC_VALIDATION"


class SchemaVersionError(SonicClueError):
    code = "SC_SCHEMA_VERSION"


class StateError(SonicClueError):
    """An operation was requested in a state that does not permit it."""

    code = "SC_STATE"


class DeviceError(SonicClueError):
    code = "SC_DEVICE"


class StorageError(SonicClueError):
    code = "SC_STORAGE"


class IntegrityError(StorageError):
    code = "SC_INTEGRITY"


class CaseLockedError(StorageError):
    code = "SC_CASE_LOCKED"


class ImportSafetyError(SonicClueError):
    code = "SC_IMPORT_UNSAFE"


class AnalysisError(SonicClueError):
    code = "SC_ANALYSIS"


class CalibrationError(SonicClueError):
    code = "SC_CALIBRATION"


class SafetyError(SonicClueError):
    """Stimulus/output safety interlock refused an operation."""

    code = "SC_OUTPUT_SAFETY"


class CancelledError(SonicClueError):
    code = "SC_CANCELLED"

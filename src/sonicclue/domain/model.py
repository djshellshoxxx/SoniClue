"""Canonical public data contracts (CON-001 .. CON-016).

These pydantic models are the single source of truth. The JSON Schemas in
docs/specs/schemas/ are *generated* from them (tools/gen_schemas.py), and CI
fails if the checked-in schemas drift (tests/test_contracts_architecture.py).

Contract-wide conventions (docs/specs/04-module-contracts.md section 2):

* Every top-level document has ``schema_version`` (semver). Readers accept
  the same major version with a minor version <= the one they implement.
  Older majors are migrated by ``sonicclue.storage.migrations``. Newer
  versions are rejected with SC_SCHEMA_VERSION (no silent partial reads).
* Unknown fields are rejected (``extra="forbid"``) so that typos and
  documents from newer versions are caught instead of silently dropped.
* Optional fields that are absent are omitted from JSON (``exclude_none``);
  JSON ``null`` carries no meaning. A *measured* value that may be
  unavailable or invalid uses ``TaggedValue``.
* Sample indices are zero-based per capture stream. Ranges are half-open
  ``[start_frame, end_frame)``. Times are timezone-aware UTC (RFC 3339).
* Frequencies are in Hz, durations in seconds, levels in dB with an explicit
  reference label, and linear values in the unit named by the channel's
  quantity (see domain.units).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .units import Quantity

SCHEMA_VERSION = "1.0.0"

Scalar = float | int | str | bool | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    """Base for all contracts: immutable and strict."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class Document(Contract):
    schema_version: str = SCHEMA_VERSION

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        try:
            major, minor, _patch = (int(p) for p in v.split("."))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"malformed schema_version {v!r}") from exc
        cur_major, cur_minor, _ = (int(p) for p in SCHEMA_VERSION.split("."))
        if major != cur_major or minor > cur_minor:
            # Raised as ValueError so pydantic reports it; storage maps it to
            # SchemaVersionError (SC_SCHEMA_VERSION).
            raise ValueError(
                f"unsupported schema_version {v}; this build reads {cur_major}.x up to {SCHEMA_VERSION}"
            )
        return v


# --------------------------------------------------------------------------
# Quality flags (CON-009)
# --------------------------------------------------------------------------


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    INVALID = "invalid"  # the affected data must not be used for the affected analysis


class QualityCode(str, Enum):
    CLIPPING = "clipping"
    NEAR_CLIPPING = "near_clipping"
    DROPOUT_GAP = "dropout_gap"
    INPUT_OVERFLOW = "input_overflow"
    SILENCE = "silence"
    LOW_SIGNAL = "low_signal"
    DC_OFFSET = "dc_offset"
    NONFINITE = "nonfinite"
    SHORT_CAPTURE = "short_capture"
    INSUFFICIENT_AVERAGES = "insufficient_averages"
    AGC_ACTIVE = "agc_active"
    AGC_UNKNOWN = "agc_unknown"
    CAL_MISSING = "cal_missing"
    CAL_GAIN_MISMATCH = "cal_gain_mismatch"
    CAL_EXPIRED = "cal_expired"
    CAL_OUT_OF_BAND = "cal_out_of_band"
    SYNC_UNVERIFIED = "sync_unverified"
    SYNC_AMBIGUOUS = "sync_ambiguous"
    SYNC_INSUFFICIENT = "sync_insufficient"
    CLOCK_RESET = "clock_reset"
    MISMATCHED_RATE = "mismatched_rate"
    NONUNIFORM_TIMESTAMPS = "nonuniform_timestamps"
    RECOVERED_CAPTURE = "recovered_capture"
    PARTIAL_CAPTURE = "partial_capture"
    DEVICE_DISCONNECTED = "device_disconnected"
    SIMULATED_DATA = "simulated_data"
    ALIAS_RISK = "alias_risk"
    TIER_LIMITED = "tier_limited"


class QualityFlag(Contract):
    code: QualityCode
    severity: Severity
    message: str = Field(max_length=500)
    channel: int | None = Field(default=None, ge=0)
    start_frame: int | None = Field(default=None, ge=0)
    end_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _range(self) -> "QualityFlag":
        if self.start_frame is not None and self.end_frame is not None and self.end_frame < self.start_frame:
            raise ValueError("end_frame must be >= start_frame (half-open range)")
        return self


class TaggedValue(Contract):
    """A measured value that may be unavailable (not measured or not applicable)
    or invalid (measured, then rejected, with a reason)."""

    status: Literal["valid", "unavailable", "invalid"]
    value: float | None = None
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _consistent(self) -> "TaggedValue":
        if self.status == "valid" and self.value is None:
            raise ValueError("valid TaggedValue requires value")
        if self.status != "valid" and not self.reason:
            raise ValueError("unavailable/invalid TaggedValue requires reason")
        return self


# --------------------------------------------------------------------------
# Sensors, placement, channels (CON-003, CON-004)
# --------------------------------------------------------------------------


class SensorKind(str, Enum):
    MEASUREMENT_MIC = "measurement_mic"
    STUDIO_MIC = "studio_mic"
    BUILTIN_MIC = "builtin_mic"
    CONTACT_PICKUP = "contact_pickup"
    PIEZO_DISC = "piezo_disc"
    ANALOG_ACCELEROMETER = "analog_accelerometer"
    MEMS_ACCELEROMETER = "mems_accelerometer"
    LINE_INPUT = "line_input"
    OTHER = "other"


# Contact pickups and piezo discs respond to strain/bending, mounting and
# airborne sound in unknown proportions. They are permanently RELATIVE and may
# never be given a physical calibration (enforced in sensors.calibration).
RELATIVE_ONLY_KINDS = frozenset({SensorKind.CONTACT_PICKUP, SensorKind.PIEZO_DISC, SensorKind.LINE_INPUT})
ACOUSTIC_KINDS = frozenset({SensorKind.MEASUREMENT_MIC, SensorKind.STUDIO_MIC, SensorKind.BUILTIN_MIC})
VIBRATION_KINDS = frozenset(
    {SensorKind.CONTACT_PICKUP, SensorKind.PIEZO_DISC, SensorKind.ANALOG_ACCELEROMETER, SensorKind.MEMS_ACCELEROMETER}
)

DEFAULT_QUANTITY = {
    SensorKind.MEASUREMENT_MIC: Quantity.SOUND_PRESSURE,
    SensorKind.STUDIO_MIC: Quantity.SOUND_PRESSURE,
    SensorKind.BUILTIN_MIC: Quantity.SOUND_PRESSURE,
    SensorKind.CONTACT_PICKUP: Quantity.RELATIVE,
    SensorKind.PIEZO_DISC: Quantity.RELATIVE,
    SensorKind.ANALOG_ACCELEROMETER: Quantity.ACCELERATION,
    SensorKind.MEMS_ACCELEROMETER: Quantity.ACCELERATION,
    SensorKind.LINE_INPUT: Quantity.RELATIVE,
    SensorKind.OTHER: Quantity.RELATIVE,
}


class SensorDescriptor(Contract):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    kind: SensorKind
    model: str = Field(default="", max_length=120)
    serial: str = Field(default="", max_length=120)
    quantity: Quantity
    axis: Literal["x", "y", "z", "normal", "omni", "unknown"] = "unknown"
    usable_band_hz: tuple[float, float] | None = None
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _kind_quantity(self) -> "SensorDescriptor":
        if self.kind in RELATIVE_ONLY_KINDS and self.quantity is not Quantity.RELATIVE:
            raise ValueError(f"{self.kind.value} sensors are relative-only; quantity must be 'relative'")
        if self.usable_band_hz and not (0 < self.usable_band_hz[0] < self.usable_band_hz[1]):
            raise ValueError("usable_band_hz must satisfy 0 < low < high")
        return self


class Mounting(str, Enum):
    STAND = "stand"
    HANDHELD = "handheld"
    WAX = "wax"
    MAGNET = "magnet"
    STUD = "stud"
    ADHESIVE = "adhesive"
    TAPE = "tape"
    CLAMP = "clamp"
    RESTING = "resting"
    UNKNOWN = "unknown"


class Placement(Contract):
    location: str = Field(default="", max_length=200)  # e.g. "desk top, left of monitor"
    position_id: str = Field(default="", max_length=64)  # stable survey position key, e.g. "P1"
    distance_m: float | None = Field(default=None, ge=0, le=1000)
    orientation: str = Field(default="", max_length=120)  # e.g. "+z normal to desk surface"
    mounting: Mounting = Mounting.UNKNOWN
    mount_surface: str = Field(default="", max_length=120)


class ChannelConfig(Contract):
    index: int = Field(ge=0, le=63)
    label: str = Field(min_length=1, max_length=64)
    sensor_id: str | None = None
    calibration_id: str | None = None
    placement: Placement = Placement()
    input_gain_db: float | None = Field(default=None, ge=-60, le=90)  # interface gain as reported by the user; None = unknown
    agc: Literal["off", "on", "unknown"] = "unknown"
    processing: list[str] = Field(default_factory=list, max_length=16)  # e.g. ["hpf_80hz"]


class DeviceInfo(Contract):
    backend: Literal["portaudio", "simulated", "file", "bridge"]
    host_api: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=200)
    device_index: int | None = None
    exclusive_mode: bool = False


# --------------------------------------------------------------------------
# Captures (CON-002)
# --------------------------------------------------------------------------


class ChunkRef(Contract):
    file: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$", max_length=128)  # relative to the capture directory; no separators
    start_frame: int = Field(ge=0)
    frames: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Gap(Contract):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    reason: Literal["input_overflow", "queue_overflow", "device_error", "dropout", "import_gap"]

    @model_validator(mode="after")
    def _range(self) -> "Gap":
        if self.end_frame < self.start_frame:
            raise ValueError("gap end_frame < start_frame")
        return self


class InterventionRecord(Contract):
    """What was physically changed. The four ``changes_*`` booleans drive the
    confound check for ADV-007. None means the user did not say."""

    description: str = Field(min_length=1, max_length=1000)
    target: str = Field(default="", max_length=120)
    changes_source_output: bool | None = None
    changes_transmission_path: bool | None = None
    changes_receiver: bool | None = None
    changes_measurement_setup: bool | None = None


class StimulusRecord(Contract):
    kind: Literal["sine", "sweep", "white", "pink", "band_noise", "impulse"]
    level_dbfs: float = Field(le=0)
    params: dict[str, float] = Field(default_factory=dict)
    output_device: str = ""


class CaptureContext(Contract):
    condition_label: str = Field(default="", max_length=120)
    equipment_state: dict[str, str] = Field(default_factory=dict)  # equipment id -> state ("on", "off", "low", ...)
    intervention: InterventionRecord | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    procedure_run_id: str | None = None
    procedure_step: str | None = None
    procedure_revision: str | None = None
    repeat_index: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=4000)


class CaptureManifest(Document):
    id: str = Field(pattern=r"^[A-Za-z0-9_\-]{6,64}$")
    case_id: str
    created_utc: datetime
    source: Literal["live", "import", "simulated"]
    device: DeviceInfo
    sample_rate_hz: float = Field(gt=0, le=768000)
    sample_format: Literal["float32"] = "float32"
    channels: list[ChannelConfig] = Field(min_length=1, max_length=64)
    frames: int = Field(ge=0)
    chunks: list[ChunkRef] = Field(default_factory=list, max_length=100000)
    gaps: list[Gap] = Field(default_factory=list)
    quality: list[QualityFlag] = Field(default_factory=list)
    clock_domain: str
    status: Literal["complete", "partial", "recovered"] = "complete"
    context: CaptureContext = CaptureContext()
    stimulus: StimulusRecord | None = None
    software_version: str

    @model_validator(mode="after")
    def _chunks_contiguous(self) -> "CaptureManifest":
        pos = 0
        for c in self.chunks:
            if c.start_frame != pos:
                raise ValueError(f"chunk {c.file} starts at {c.start_frame}, expected {pos} (chunks must be contiguous)")
            pos += c.frames
        if self.chunks and pos != self.frames:
            raise ValueError(f"chunk frames sum {pos} != frames {self.frames}")
        idx = [ch.index for ch in self.channels]
        if len(set(idx)) != len(idx):
            raise ValueError("duplicate channel index")
        return self

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate_hz


# --------------------------------------------------------------------------
# Calibration (CON-005)
# --------------------------------------------------------------------------


class FrPoint(Contract):
    freq_hz: float = Field(gt=0)
    correction_db: float = Field(ge=-60, le=60)


class CalibrationProfile(Document):
    """``sensitivity_fs_per_unit``: digital RMS (FS) produced by 1 unit RMS of the
    physical quantity at ``reference_freq_hz`` with the interface gain at
    ``reference_gain_db``. Conversion: physical = FS / sensitivity (INV-006).

    ``fr_correction`` holds dB values to ADD to a level measured in physical
    units to obtain the true level (true_db = measured_db + correction_db),
    interpolated linearly in dB over log-frequency. It is only valid inside
    ``valid_band_hz``."""

    id: str = Field(pattern=r"^[A-Za-z0-9_\-]{3,64}$")
    sensor_id: str
    quantity: Quantity
    sensitivity_fs_per_unit: float = Field(gt=0, le=1e6)
    reference_freq_hz: float = Field(gt=0)
    reference_gain_db: float | None = None
    fr_correction: list[FrPoint] = Field(default_factory=list, max_length=4096)
    valid_band_hz: tuple[float, float]
    uncertainty_db: float = Field(ge=0, le=20)  # expanded uncertainty, k=2
    method: Literal["calibrator", "manufacturer_sheet", "comparison", "manual"]
    source_capture_id: str | None = None
    device_name: str = ""
    created_utc: datetime
    expires_utc: datetime | None = None
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _checks(self) -> "CalibrationProfile":
        if self.quantity is Quantity.RELATIVE:
            raise ValueError("a calibration profile must map to a physical quantity, not 'relative'")
        lo, hi = self.valid_band_hz
        if not (0 < lo < hi):
            raise ValueError("valid_band_hz must satisfy 0 < low < high")
        f = [p.freq_hz for p in self.fr_correction]
        if f != sorted(f) or len(set(f)) != len(f):
            raise ValueError("fr_correction frequencies must be strictly increasing")
        return self


# --------------------------------------------------------------------------
# Clock mapping (CON-008)
# --------------------------------------------------------------------------


class ClockMapping(Document):
    """Maps frame indices of capture ``other`` onto the timeline of ``reference``:
    t_ref = offset_s + (1 + drift_ppm*1e-6) * n_other / fs_other."""

    id: str
    reference_capture_id: str
    other_capture_id: str
    basis: Literal["shared_clock", "common_event", "hardware_timestamp", "host_timestamp"]
    offset_s: float
    drift_ppm: float = Field(ge=-2000, le=2000)
    residual_s: float = Field(ge=0)  # RMS timing residual (1 sigma)
    ambiguity_ratio: float = Field(ge=0, le=1)  # second peak / main peak of the correlation
    valid_from_s: float = 0.0
    valid_to_s: float
    eligible_max_freq_hz: float = Field(ge=0)  # synchronized analysis allowed below this frequency
    method: str
    created_utc: datetime


# --------------------------------------------------------------------------
# Analysis (CON-006, CON-007)
# --------------------------------------------------------------------------


WindowName = Literal["hann", "hamming", "blackmanharris", "flattop", "boxcar"]


class AnalysisConfig(Contract):
    window: WindowName = "hann"
    resolution_hz: float = Field(default=1.0, gt=0, le=100)  # target bin spacing; reduced if averages are insufficient
    overlap: float = Field(default=0.5, ge=0, lt=0.95)
    min_averages: int = Field(default=8, ge=1, le=10000)
    min_nperseg: int = Field(default=256, ge=16)
    fmin_hz: float = Field(default=10.0, ge=0)
    fmax_hz: float | None = Field(default=None, gt=0)
    tone_prominence_db: float = Field(default=10.0, ge=3, le=60)
    max_peaks: int = Field(default=25, ge=1, le=500)
    event_threshold_db: float = Field(default=8.0, ge=3, le=60)
    event_frame_s: float = Field(default=0.01, gt=0, le=1)
    band_type: Literal["octave", "third_octave"] = "third_octave"
    coherence_alpha: float = Field(default=0.05, gt=0, lt=0.5)
    spectrogram_nperseg: int = Field(default=4096, ge=64)
    store_arrays: bool = True


class LevelSummary(Contract):
    rms: float = Field(ge=0)
    peak: float = Field(ge=0)
    crest_db: TaggedValue
    level_db: float
    level_ref: str
    unit: str
    calibrated: bool
    dc_offset_fs: float


class TonalPeak(Contract):
    freq_hz: float = Field(gt=0)
    level_db: float
    prominence_db: float
    rms: float = Field(ge=0)
    q: TaggedValue  # f0 / -3 dB bandwidth when resolvable
    cal_in_band: bool = True


class HarmonicFamily(Contract):
    f0_hz: float = Field(gt=0)
    orders: list[int] = Field(min_length=2)
    mains: Literal["50", "60", "none"] = "none"


class TransientSummary(Contract):
    event_count: int = Field(ge=0)
    events_per_min: float = Field(ge=0)
    median_interval_s: TaggedValue
    periodic: bool
    max_excess_db: float
    event_times_s: list[float] = Field(default_factory=list, max_length=2000)


class BandLevel(Contract):
    center_hz: float
    low_hz: float
    high_hz: float
    level_db: float
    power: float = Field(ge=0)
    valid: bool  # False if the band extends outside the analysed range or calibration band


class ChannelAnalysis(Contract):
    channel: int
    label: str
    quantity: Quantity
    unit: str
    calibrated: bool
    levels: LevelSummary
    noise_floor_db: float
    peaks: list[TonalPeak]
    families: list[HarmonicFamily]
    transients: TransientSummary
    bands: list[BandLevel]
    n_averages: int
    nperseg: int
    resolution_hz: float
    enbw_hz: float
    excluded_frames: int = Field(ge=0)
    quality: list[QualityFlag] = Field(default_factory=list)


class CoherentPeak(Contract):
    freq_hz: float
    coherence: float = Field(ge=0, le=1)
    transfer_db: float
    phase_rad: float


class CrossChannelResult(Contract):
    ch_a: int
    ch_b: int
    sync_basis: Literal["shared_clock", "aligned", "none"]
    eligible: bool
    reason: str
    max_valid_freq_hz: float = Field(ge=0)
    n_averages: int
    coherence_threshold: float = Field(ge=0, le=1)
    delay_s: TaggedValue
    delay_ambiguity_ratio: float = Field(ge=0, le=1)
    coherent_peaks: list[CoherentPeak] = Field(default_factory=list)


class AnalysisResult(Document):
    id: str
    capture_id: str
    created_utc: datetime
    config: AnalysisConfig
    algorithm_version: str
    tier: int = Field(ge=1, le=5)
    channels: list[ChannelAnalysis]
    cross: list[CrossChannelResult] = Field(default_factory=list)
    arrays_file: str | None = None
    quality: list[QualityFlag] = Field(default_factory=list)
    software_version: str


# --------------------------------------------------------------------------
# Comparisons
# --------------------------------------------------------------------------


class ComparabilityIssue(Contract):
    field: str
    a: str
    b: str
    effect: Literal["invalidates", "caveat"]
    message: str


class BandDelta(Contract):
    center_hz: float
    delta_db: float
    uncertainty_db: float = Field(ge=0)
    significant: bool


class ToneDelta(Contract):
    freq_hz: float
    level_a_db: float | None = None
    level_b_db: float | None = None
    delta_db: float | None = None
    status: Literal["reduced", "increased", "unchanged", "disappeared", "appeared"]


class ComparisonResult(Document):
    """Delta convention: delta = B - A in dB (negative means quieter in B)."""

    id: str
    case_id: str
    kind: Literal["state", "intervention", "generic"] = "generic"
    procedure_run_id: str | None = None
    label_a: str
    label_b: str
    captures_a: list[str] = Field(min_length=1)
    captures_b: list[str] = Field(min_length=1)
    channel_label: str
    comparable: bool
    issues: list[ComparabilityIssue] = Field(default_factory=list)
    overall_delta_db: float
    overall_uncertainty_db: float = Field(ge=0)
    overall_significant: bool
    repeatability: Literal["measured", "estimated"]
    band_deltas: list[BandDelta] = Field(default_factory=list)
    tone_deltas: list[ToneDelta] = Field(default_factory=list)
    changed_equipment: dict[str, list[str]] = Field(default_factory=dict)  # id -> [state_a, state_b]
    intervention: InterventionRecord | None = None
    algorithm_version: str
    created_utc: datetime


# --------------------------------------------------------------------------
# Procedures (CON-010, CON-011)
# --------------------------------------------------------------------------


class ProcStep(Contract):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    kind: Literal["instruction", "capture", "intervention"]
    title: str
    instruction: str  # plain-language (guided mode); may contain {param} placeholders
    expert_note: str = ""
    condition_label: str = ""
    equipment_state: dict[str, str] = Field(default_factory=dict)  # keys may be "{target}"
    position_id: str = ""
    mounting: Mounting | None = None  # overrides the sensor channel's mounting for this step (e.g. airborne control)
    sample_rate_hz: float | None = Field(default=None, gt=0)  # alias check captures at a different rate
    stimulus: StimulusRecord | None = None  # played (after explicit arming) during the capture
    settle_s: float = Field(default=0, ge=0, le=3600)
    duration_s: float = Field(default=0, ge=0, le=3600)
    repeats: int = Field(default=1, ge=1, le=20)
    gates: list[Literal["no_clipping", "signal_present", "comparable_to_first", "sync_shared_clock"]] = Field(
        default_factory=list
    )


class ProcedureDef(Contract):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    revision: str
    title: str
    purpose: str
    min_tier: int = Field(ge=1, le=5)
    required_sensors: list[Literal["acoustic", "vibration", "any"]] = Field(default_factory=lambda: ["any"])
    parameters: list[Literal["target", "object"]] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    confounds: list[str] = Field(default_factory=list)
    safety: list[str] = Field(default_factory=list)
    steps: list[ProcStep] = Field(min_length=1)
    analysis: Literal[
        "baseline",
        "state_comparison",
        "position_survey",
        "contact_survey",
        "intervention",
        "resonance",
        "chain_noise",
        "alias_check",
        "airborne_control",
        "speaker_buzz",
    ]
    success: str
    difficulty: int = Field(ge=1, le=3)


class ProcedureRun(Document):
    id: str
    case_id: str
    procedure_id: str
    revision: str
    params: dict[str, str] = Field(default_factory=dict)
    state: Literal["running", "paused", "completed", "cancelled", "failed"]
    step_index: int = Field(ge=0)
    repeat_index: int = Field(ge=0)
    captures: dict[str, list[str]] = Field(default_factory=dict)  # step id -> capture ids in repeat order
    interventions: dict[str, InterventionRecord] = Field(default_factory=dict)
    started_utc: datetime
    updated_utc: datetime
    outcome: str = ""
    failure_reason: str = ""


# --------------------------------------------------------------------------
# Evidence, hypotheses, diagnosis (CON-012, CON-013)
# --------------------------------------------------------------------------


class StatementClass(str, Enum):
    MEASURED = "measured"
    CALCULATED = "calculated"
    INFERRED = "inferred"
    USER_ASSERTED = "user_asserted"
    UNRESOLVED = "unresolved"


class EvidenceKind(str, Enum):
    TONE = "tone"
    HARMONIC_FAMILY = "harmonic_family"
    MAINS_HARMONICS = "mains_harmonics"
    STATE_EFFECT = "state_effect"  # turning equipment off/on changed the level significantly
    NO_STATE_EFFECT = "no_state_effect"
    RESIDUAL_AFTER_OFF = "residual_after_off"  # something remains with the equipment off
    STRUCTURAL_COHERENCE = "structural_coherence"
    AIRBORNE_CONTROL = "airborne_control"
    RESONANCE = "resonance"
    TRANSIENTS = "transients"
    POSITION_GRADIENT = "position_gradient"
    INTERVENTION_EFFECT = "intervention_effect"
    CONFOUNDED_INTERVENTION = "confounded_intervention"
    NOT_COMPARABLE = "not_comparable"
    MEASUREMENT_QUALITY = "measurement_quality"
    ALIAS_TEST = "alias_test"
    CHAIN_NOISE_TEST = "chain_noise_test"
    USER_OBSERVATION = "user_observation"


class EvidenceItem(Contract):
    id: str
    kind: EvidenceKind
    statement_class: StatementClass
    summary: str
    params: dict[str, Scalar] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    channel_label: str | None = None
    freq_hz: float | None = None
    valid: bool = True


class SupportLevel(str, Enum):
    STRONG = "strongly_supported"
    SUPPORTED = "supported"
    UNDETERMINED = "undetermined"
    WEAKENED = "weakened"
    CONTRADICTED = "contradicted"


SUPPORT_ORDER = {
    SupportLevel.STRONG: 4,
    SupportLevel.SUPPORTED: 3,
    SupportLevel.UNDETERMINED: 2,
    SupportLevel.WEAKENED: 1,
    SupportLevel.CONTRADICTED: 0,
}


class HypothesisCategory(str, Enum):
    SOURCE = "source"
    ADDITIONAL_SOURCE = "additional_source"
    STRUCTURAL_PATH = "structural_path"
    AIRBORNE_PATH = "airborne_path"
    RESONANCE = "resonance"
    RATTLE = "rattle"
    ELECTRICAL_HUM = "electrical_hum"
    RECORDING_CHAIN = "recording_chain"
    MEASUREMENT_ARTIFACT = "measurement_artifact"


class Hypothesis(Contract):
    id: str
    category: HypothesisCategory
    subject: str
    freq_hz: float | None = None
    statement: str
    level: SupportLevel
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    missing_tests: list[str] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)  # "RULE-ID@revision"
    explanation: list[str] = Field(default_factory=list)


class NextTest(Contract):
    procedure_id: str
    title: str
    params: dict[str, str] = Field(default_factory=dict)
    reason: str
    discriminates: list[str] = Field(default_factory=list)
    pairs_separated: int = Field(ge=0)
    difficulty: int = Field(ge=1, le=3)
    available: bool
    unavailable_reason: str = ""


class DiagnosisSnapshot(Document):
    id: str
    case_id: str
    created_utc: datetime
    ruleset_version: str
    conclusion: Literal["leading_explanation", "multiple_explanations", "inconclusive"]
    abstention_reasons: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem]
    hypotheses: list[Hypothesis]
    next_tests: list[NextTest]


# --------------------------------------------------------------------------
# Case (CON-001)
# --------------------------------------------------------------------------


class Equipment(Contract):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["fan", "computer", "hvac", "speaker", "amplifier", "machine", "appliance", "lighting", "power", "other"]
    notes: str = Field(default="", max_length=1000)


ProblemCharacter = Literal[
    "hum", "buzz", "rattle", "whine", "rumble", "tonal", "broadband", "intermittent", "continuous", "felt_vibration"
]


class ProblemDescription(Contract):
    summary: str = Field(default="", max_length=4000)
    character: list[ProblemCharacter] = Field(default_factory=list)
    receiver: str = Field(default="", max_length=200)  # what is affected: "vocal mic", "listening position"
    approx_band_hz: tuple[float, float] | None = None
    when: str = Field(default="", max_length=500)


class Case(Document):
    id: str = Field(pattern=r"^[A-Za-z0-9_\-]{6,64}$")
    title: str = Field(min_length=1, max_length=200)
    created_utc: datetime
    updated_utc: datetime
    problem: ProblemDescription = ProblemDescription()
    equipment: list[Equipment] = Field(default_factory=list, max_length=200)
    sensors: list[SensorDescriptor] = Field(default_factory=list, max_length=200)
    notes: str = Field(default="", max_length=20000)

    def equipment_ids(self) -> set[str]:
        return {e.id for e in self.equipment}


class Annotation(Contract):
    id: str
    case_id: str
    target: str  # case | capture id | hypothesis id
    text: str = Field(min_length=1, max_length=4000)
    created_utc: datetime


# --------------------------------------------------------------------------
# Reports and archives (CON-014, CON-015)
# --------------------------------------------------------------------------


class ReportStatement(Contract):
    cls: StatementClass
    text: str
    refs: list[str] = Field(default_factory=list)


class ReportTable(Contract):
    title: str
    columns: list[str]
    rows: list[list[str]]


class ReportSection(Contract):
    key: str
    title: str
    statements: list[ReportStatement] = Field(default_factory=list)
    tables: list[ReportTable] = Field(default_factory=list)
    figures: list[str] = Field(default_factory=list)  # figure keys; images are rendered per format


class ReportDocument(Document):
    id: str
    case_id: str
    report_version: int = Field(ge=1)
    created_utc: datetime
    software_version: str
    ruleset_version: str
    redactions: list[str] = Field(default_factory=list)
    case_digest: str
    sections: list[ReportSection]


class ArchiveEntry(Contract):
    path: str = Field(max_length=300)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArchiveManifest(Document):
    format: Literal["sonicclue-case-archive"] = "sonicclue-case-archive"
    case_id: str
    created_utc: datetime
    software_version: str
    entries: list[ArchiveEntry] = Field(max_length=200000)


# --------------------------------------------------------------------------
# Sensor bridge (CON-016): JSON form of decoded bridge packets
# --------------------------------------------------------------------------


class BridgeHello(Contract):
    type: Literal["hello"] = "hello"
    protocol_version: int = Field(ge=1, le=255)
    device_model: str = Field(max_length=32)
    firmware_version: str = Field(max_length=32)
    sample_rate_hz: float = Field(gt=0, le=100000)
    axes: int = Field(ge=1, le=3)
    full_scale_g: float = Field(gt=0, le=1000)


class BridgeData(Contract):
    type: Literal["data"] = "data"
    seq: int = Field(ge=0, le=65535)
    sample_counter: int = Field(ge=0, le=2**32 - 1)
    device_time_us: int = Field(ge=0, le=2**64 - 1)
    axes: int = Field(ge=1, le=3)
    samples: list[list[int]] = Field(max_length=512)  # [n][axes] raw int16 counts


class BridgeError(Contract):
    type: Literal["error"] = "error"
    code: int = Field(ge=0, le=255)
    message: str = Field(max_length=64)


BridgeMessage = BridgeHello | BridgeData | BridgeError

DOCUMENT_TYPES: dict[str, type[BaseModel]] = {
    "case": Case,
    "capture_manifest": CaptureManifest,
    "calibration_profile": CalibrationProfile,
    "clock_mapping": ClockMapping,
    "analysis_result": AnalysisResult,
    "comparison_result": ComparisonResult,
    "procedure_run": ProcedureRun,
    "diagnosis_snapshot": DiagnosisSnapshot,
    "report": ReportDocument,
    "archive_manifest": ArchiveManifest,
}

CONTRACT_TYPES: dict[str, type[BaseModel]] = {
    **DOCUMENT_TYPES,
    "sensor_descriptor": SensorDescriptor,
    "channel_config": ChannelConfig,
    "quality_flag": QualityFlag,
    "analysis_config": AnalysisConfig,
    "procedure_definition": ProcedureDef,
    "evidence_item": EvidenceItem,
    "hypothesis": Hypothesis,
    "bridge_hello": BridgeHello,
    "bridge_data": BridgeData,
    "bridge_error": BridgeError,
}


def dump_json(model: BaseModel) -> str:
    return model.model_dump_json(exclude_none=True, indent=2)


def dump_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=True)

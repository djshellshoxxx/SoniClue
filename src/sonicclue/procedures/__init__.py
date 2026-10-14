"""Guided procedure library and executor (docs/specs/10-guided-procedures.md).

Procedures are declarative (``definitions/procedures.json``, validated as
ProcedureDef). The executor is a pure state machine over ProcedureRun
documents. It never touches devices: the application service performs
captures, evaluates gates and calls ``record_capture``. Every transition
returns a new immutable run, which the caller persists, so a crash at any
point resumes from the last persisted step (the "running" state is persisted
and reopened as "paused").

State machine (SM-003):

    running --pause--> paused --resume--> running
    running --(last step done)--> completed
    running|paused --cancel--> cancelled
    running --fail(reason)--> failed
    terminal states (completed, cancelled, failed) accept no events (SC_STATE).
"""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from importlib import resources

from ..domain.errors import StateError, ValidationError
from ..domain.model import InterventionRecord, ProcedureDef, ProcedureRun, ProcStep, utcnow

TERMINAL = {"completed", "cancelled", "failed"}


@lru_cache(maxsize=1)
def library() -> dict[str, ProcedureDef]:
    raw = json.loads(resources.files("sonicclue.procedures").joinpath("definitions/procedures.json").read_text("utf-8"))
    defs = [ProcedureDef.model_validate(d) for d in raw]
    ids = [d.id for d in defs]
    if len(set(ids)) != len(ids):
        raise ValidationError("duplicate procedure ids")
    return {d.id: d for d in defs}


def get(proc_id: str) -> ProcedureDef:
    try:
        return library()[proc_id]
    except KeyError:
        raise ValidationError(f"unknown procedure {proc_id!r}", code="SC_UNKNOWN_PROCEDURE") from None


def fill(text: str, params: dict[str, str]) -> str:
    for k, v in params.items():
        text = text.replace("{" + k + "}", v)
    return text


def resolved_step(d: ProcedureDef, idx: int, params: dict[str, str]) -> ProcStep:
    s = d.steps[idx]
    data = s.model_dump()
    for key in ("title", "instruction", "expert_note", "condition_label"):
        data[key] = fill(data[key], params)
    data["equipment_state"] = {fill(k, params): fill(v, params) for k, v in s.equipment_state.items()}
    return ProcStep.model_validate(data)


def start(case_id: str, d: ProcedureDef, params: dict[str, str]) -> ProcedureRun:
    missing = [p for p in d.parameters if not params.get(p)]
    if missing:
        raise ValidationError(f"procedure {d.id} needs parameter(s): {', '.join(missing)}", code="SC_PROCEDURE_PARAMS")
    now = utcnow()
    return ProcedureRun(id=f"run-{uuid.uuid4().hex[:12]}", case_id=case_id, procedure_id=d.id, revision=d.revision,
                        params=dict(params), state="running", step_index=0, repeat_index=0, started_utc=now, updated_utc=now)


def _upd(run: ProcedureRun, **kw) -> ProcedureRun:
    return run.model_copy(update={**kw, "updated_utc": utcnow()})


def _require(run: ProcedureRun, *states: str) -> None:
    if run.state not in states:
        raise StateError(f"procedure run is {run.state}; expected {'/'.join(states)}")


def current(run: ProcedureRun) -> tuple[ProcStep | None, int]:
    d = get(run.procedure_id)
    if run.step_index >= len(d.steps):
        return None, 0
    return resolved_step(d, run.step_index, run.params), run.repeat_index


def _advance(run: ProcedureRun) -> ProcedureRun:
    d = get(run.procedure_id)
    nxt = run.step_index + 1
    if nxt >= len(d.steps):
        return _upd(run, step_index=nxt, repeat_index=0, state="completed")
    return _upd(run, step_index=nxt, repeat_index=0)


def acknowledge(run: ProcedureRun) -> ProcedureRun:
    """Complete an instruction step."""
    _require(run, "running")
    step, _ = current(run)
    if step is None or step.kind != "instruction":
        raise StateError("current step is not an instruction")
    return _advance(run)


def record_intervention(run: ProcedureRun, record: InterventionRecord) -> ProcedureRun:
    _require(run, "running")
    step, _ = current(run)
    if step is None or step.kind != "intervention":
        raise StateError("current step is not an intervention")
    iv = dict(run.interventions)
    iv[step.id] = record
    return _advance(run.model_copy(update={"interventions": iv}))


def record_capture(run: ProcedureRun, capture_id: str, accepted: bool) -> ProcedureRun:
    """Register a capture for the current step. Rejected captures (failed gates)
    are kept under ``<step>__rejected`` for traceability, and the step repeats."""
    _require(run, "running")
    step, rep = current(run)
    if step is None or step.kind != "capture":
        raise StateError("current step is not a capture step")
    caps = {k: list(v) for k, v in run.captures.items()}
    key = step.id if accepted else f"{step.id}__rejected"
    caps.setdefault(key, []).append(capture_id)
    run = run.model_copy(update={"captures": caps})
    if not accepted:
        return _upd(run)
    if rep + 1 < step.repeats:
        return _upd(run, repeat_index=rep + 1)
    return _advance(run)


def latest_intervention(run: ProcedureRun) -> InterventionRecord | None:
    return list(run.interventions.values())[-1] if run.interventions else None


def pause(run: ProcedureRun) -> ProcedureRun:
    _require(run, "running")
    return _upd(run, state="paused")


def resume(run: ProcedureRun) -> ProcedureRun:
    _require(run, "paused")
    return _upd(run, state="running")


def cancel(run: ProcedureRun) -> ProcedureRun:
    _require(run, "running", "paused")
    return _upd(run, state="cancelled")


def fail(run: ProcedureRun, reason: str) -> ProcedureRun:
    _require(run, "running", "paused")
    return _upd(run, state="failed", failure_reason=reason[:500])


def complete_with_outcome(run: ProcedureRun, outcome: str) -> ProcedureRun:
    return run.model_copy(update={"outcome": outcome[:2000]})


def progress(run: ProcedureRun) -> tuple[int, int]:
    d = get(run.procedure_id)
    return min(run.step_index, len(d.steps)), len(d.steps)

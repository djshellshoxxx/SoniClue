"""Demo investigation on the built-in simulator.

Everything here goes through the public application services, the same
path the GUI and CLI use. The resulting case is clearly marked SIMULATED in
every capture, analysis and report. It exists for training, demonstration
and end-to-end testing. It is not evidence about any real room.
"""

from __future__ import annotations

from typing import Callable

from ..domain.model import (
    CaptureContext,
    ChannelConfig,
    Equipment,
    InterventionRecord,
    Mounting,
    Placement,
    ProblemDescription,
    SensorDescriptor,
    SensorKind,
)
from ..domain.units import Quantity
from .service import CaptureSpec, SonicClueApp


def demo_channels() -> list[ChannelConfig]:
    return [
        ChannelConfig(index=0, label="mic", sensor_id="mic1", agc="off", input_gain_db=30.0,
                      placement=Placement(location="vocal position, 40 cm above desk", position_id="P1", mounting=Mounting.STAND)),
        ChannelConfig(index=1, label="desk", sensor_id="contact1", agc="off", input_gain_db=20.0,
                      placement=Placement(location="desk top near computer", position_id="C1", mounting=Mounting.WAX)),
    ]


def run_demo(app: SonicClueApp, progress: Callable[[str], None] = print, duration_scale: float = 1.0) -> str:
    cid = app.create_case(
        "DEMO (simulated): low hum in home-studio vocal recordings",
        problem=ProblemDescription(summary="A low hum/whine is audible on vocal recordings at the desk.",
                                   character=["hum", "tonal", "continuous"], receiver="desk vocal microphone"),
        equipment=[Equipment(id="pc", name="Desktop computer", kind="computer"),
                   Equipment(id="hvac", name="Air conditioner", kind="hvac")],
        sensors=[SensorDescriptor(id="mic1", kind=SensorKind.STUDIO_MIC, model="generic condenser", quantity=Quantity.SOUND_PRESSURE),
                 SensorDescriptor(id="contact1", kind=SensorKind.CONTACT_PICKUP, model="piezo contact pickup", quantity=Quantity.RELATIVE)])
    base = CaptureSpec(channels=demo_channels(), duration_s=10 * duration_scale, backend="simulated", device=0,
                       context=CaptureContext(equipment_state={"pc": "on", "hvac": "on", "input": "connected"}))
    app.sim.world.state = dict(base.context.equipment_state)

    def run_proc(pid, params=None, intervention=None):
        run = app.start_procedure(pid, params or {})
        progress(f"procedure {pid} {params or ''}")
        while run.state == "running":
            from .. import procedures

            step, rep = procedures.current(run)
            if step.kind == "instruction":
                run = app.procedure_action(run.id, "ack")
            elif step.kind == "intervention":
                run = app.procedure_action(run.id, "intervention", record=intervention)
                # the simulated world reflects the physical change the user just made
                app.sim.world.pc_isolated = bool(intervention and "pad" in intervention.description)
            else:
                spec = base
                if step.duration_s:
                    spec = CaptureSpec(**{**base.__dict__, "duration_s": max(2.0, step.duration_s * duration_scale)})
                run, m, failed = app.run_step_capture(run.id, spec)
                progress(f"  {step.title} #{rep + 1}: {m.id if m else '-'} {'OK' if not failed else failed}")
        return run

    run_proc("baseline")
    run_proc("equipment_state", {"target": "pc"})
    run_proc("equipment_state", {"target": "hvac"})
    run_proc("airborne_control")
    run_proc("isolation_comparison", {"target": "pc"},
             InterventionRecord(description="rubber isolation pads under the computer", target="pc",
                                changes_source_output=False, changes_transmission_path=True, changes_receiver=False,
                                changes_measurement_setup=False))
    app.sim.world.pc_isolated = False
    snap = app.diagnose()
    progress(f"diagnosis: {snap.conclusion}")
    for h in snap.hypotheses[:6]:
        progress(f"  [{h.level.value}] {h.statement}")
    return cid

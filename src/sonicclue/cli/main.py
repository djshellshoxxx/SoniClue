"""SonicClue command-line interface (docs/specs/12-gui-and-user-experience.md section 9).

Every command uses ``SonicClueApp``, the same services as the GUI. Exit codes:
0 ok, 1 usage/validation error, 2 runtime/device error, 3 integrity problem,
130 interrupted. ``--json`` prints machine-readable output where supported.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .. import BUILD_ID, __version__, procedures
from ..domain.errors import SonicClueError, ValidationError
from ..domain.model import (
    AnalysisConfig,
    CaptureContext,
    ChannelConfig,
    Equipment,
    InterventionRecord,
    Mounting,
    Placement,
    ProblemDescription,
    SensorDescriptor,
    SensorKind,
    StimulusRecord,
    DEFAULT_QUANTITY,
    dump_dict,
)


def _app(args):
    from ..app.service import SonicClueApp

    return SonicClueApp(Path(args.workspace) if args.workspace else None, sim_speed=args.sim_speed)


def _print(args, obj, text=None):
    if args.json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        print(text if text is not None else obj)


def _kv(items: list[str] | None) -> dict[str, str]:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise ValidationError(f"expected key=value, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _channels(args, app) -> list[ChannelConfig]:
    """--ch "0:label[:sensor[:position[:mounting[:gain_db[:agc[:calibration]]]]]]" (repeatable)."""
    chans = []
    for spec in args.ch or ["0:mic"]:
        p = spec.split(":")
        idx, label = int(p[0]), p[1] if len(p) > 1 else f"ch{p[0]}"
        sensor = p[2] if len(p) > 2 and p[2] else None
        pos = p[3] if len(p) > 3 else ""
        mount = Mounting(p[4]) if len(p) > 4 and p[4] else Mounting.UNKNOWN
        gain = float(p[5]) if len(p) > 5 and p[5] else None
        agc = p[6] if len(p) > 6 and p[6] else "unknown"
        calid = p[7] if len(p) > 7 and p[7] else None
        chans.append(ChannelConfig(index=idx, label=label, sensor_id=sensor, calibration_id=calid, input_gain_db=gain, agc=agc,
                                   placement=Placement(position_id=pos, mounting=mount)))
    return chans


def _spec(args, app, context=None):
    from ..app.service import CaptureSpec

    return CaptureSpec(channels=_channels(args, app), duration_s=args.duration, backend=args.backend, device=args.device,
                       samplerate=args.rate, exclusive=getattr(args, "exclusive", False),
                       context=context or CaptureContext(condition_label=getattr(args, "label", "") or "",
                                                         equipment_state=_kv(getattr(args, "state", None))))


# ------------------------------------------------------------------ commands


def cmd_info(args):
    app = _app(args)
    _print(args, app.environment(), "\n".join(f"{k}: {v}" for k, v in app.environment().items()))


def cmd_selftest(args):
    app = _app(args)
    res = app.selftest()
    _print(args, res, "\n".join(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}" for r in res))
    return 0 if all(r["passed"] for r in res) else 3


def cmd_devices(args):
    app = _app(args)
    devs = app.devices(args.backend)
    _print(args, [d.__dict__ for d in devs], "\n".join(
        f"[{d.index}] {d.name} ({d.host_api}) in:{d.max_input_channels} out:{d.max_output_channels} {d.default_samplerate:g} Hz"
        for d in devs) or "no devices found")


def cmd_case(args):
    app = _app(args)
    if args.action == "list":
        cs = app.list_cases()
        _print(args, cs, "\n".join(f"{c['id']}  {c['title']}  ({c['captures']} captures){'  LOCKED' if c['locked'] else ''}"
                                   f"{'  ERROR: ' + c['error'] if c['error'] else ''}" for c in cs) or "no cases")
        return
    if args.action == "new":
        eq = []
        for e in args.equipment or []:
            eid, _, rest = e.partition("=")
            name, _, kind = rest.partition(":")
            eq.append(Equipment(id=eid, name=name or eid, kind=kind or "other"))
        sensors = []
        for s in args.sensor or []:
            sid, _, kind = s.partition("=")
            k = SensorKind(kind)
            sensors.append(SensorDescriptor(id=sid, kind=k, quantity=DEFAULT_QUANTITY[k]))
        prob = ProblemDescription(summary=args.summary or "", character=args.character or [], receiver=args.receiver or "")
        cid = app.create_case(args.title, prob, eq, sensors)
        _print(args, {"case_id": cid}, cid)
        app.close_case()
        return
    app.open_case(args.case)
    try:
        if args.action == "show":
            c = app.case()
            caps = app.captures()
            _print(args, {"case": dump_dict(c), "captures": [dump_dict(m) for m in caps]},
                   f"{c.title} [{c.id}]\nproblem: {c.problem.summary}\nequipment: {', '.join(e.id for e in c.equipment)}\n"
                   f"sensors: {', '.join(f'{s.id}({s.kind.value})' for s in c.sensors)}\ncaptures:\n" +
                   "\n".join(f"  {m.id} {m.context.condition_label or '-'} {m.duration_s:.1f}s {m.source} {m.status}" for m in caps))
        elif args.action == "verify":
            probs = app.verify_case()
            _print(args, probs, "\n".join(probs) or "OK: database, documents and all capture checksums verified")
            return 3 if probs else 0
        elif args.action == "annotate":
            a = app.annotate(args.target or "case", args.text)
            _print(args, dump_dict(a), a.id)
        elif args.action == "history":
            log = app.store.audit_log(args.limit)
            _print(args, log, "\n".join(f"{r['ts'][:19]} {r['action']:<22} {r['target']} {r['detail']}" for r in reversed(log)))
    finally:
        app.close_case()


def cmd_capture(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        spec = _spec(args, app)
        h = app.start_capture(spec)
        t0 = time.monotonic()
        try:
            while h.state.value in ("running", "stopping"):
                snap = h.session.snapshot()
                if not args.json:
                    meters = " ".join(f"{p:6.1f}" for p in snap.peak_dbfs)
                    print(f"\r{snap.seconds:6.1f}s peak dBFS [{meters}] gaps {snap.gaps} {'CLIP' if any(snap.clipped) else ''}   ",
                          end="", flush=True)
                time.sleep(0.25)
                if time.monotonic() - t0 > args.duration * 3 + 30:
                    h.stop()
        except KeyboardInterrupt:
            h.stop()
        m = h.finalize(timeout=30)
        if not args.json:
            print()
        if m is None:
            _print(args, {"cancelled": True}, "capture discarded")
            return 1
        if args.analyze:
            app.analyze(m.id)
        _print(args, dump_dict(m), f"saved {m.id} ({m.duration_s:.1f} s, {m.status}); flags: "
                                   f"{', '.join(q.code.value for q in m.quality) or 'none'}")
    finally:
        app.close_case()


def cmd_import(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        ctx = CaptureContext(condition_label=args.label or "", equipment_state=_kv(args.state))
        if args.bridge:
            m = app.import_bridge(Path(args.file), args.sensor, ctx)
        else:
            m = app.import_audio(Path(args.file), _channels(args, app) if args.ch else None, ctx)
        if args.analyze:
            app.analyze(m.id)
        _print(args, dump_dict(m), f"imported {m.id} ({m.duration_s:.1f} s, {len(m.channels)} ch)")
    finally:
        app.close_case()


def cmd_analyze(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        cfg = app.analysis_config()
        if args.resolution:
            cfg = cfg.model_copy(update={"resolution_hz": args.resolution})
        if args.window:
            cfg = cfg.model_copy(update={"window": args.window})
        AnalysisConfig.model_validate(cfg.model_dump())
        ids = args.capture or [m.id for m in app.captures()]
        out = []
        for cid in ids:
            a = app.analyze(cid, cfg)
            out.append(dump_dict(a))
            if not args.json:
                print(f"{cid}: tier {a.tier}")
                for ch in a.channels:
                    tones = ", ".join(f"{p.freq_hz:.1f} Hz (+{p.prominence_db:.0f} dB)" for p in ch.peaks[:6]) or "none"
                    print(f"  {ch.label}: {ch.levels.level_db:.1f} {ch.levels.level_ref}; tones {tones}; "
                          f"{ch.n_averages} averages; flags {', '.join(q.code.value for q in ch.quality) or 'none'}")
                for cr in a.cross:
                    print(f"  cross {cr.ch_a}-{cr.ch_b}: {'eligible' if cr.eligible else 'NOT eligible'} ({cr.reason}); "
                          f"coherent at {', '.join(f'{c.freq_hz:.0f}' for c in cr.coherent_peaks) or '-'}")
        if args.json:
            _print(args, out)
    finally:
        app.close_case()


def cmd_compare(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        band = tuple(args.band) if args.band else None
        c = app.compare(args.a, args.b, args.channel, label_a=args.label_a, label_b=args.label_b, band=band)
        lines = [f"{c.label_a} -> {c.label_b} [{c.channel_label}]: {c.overall_delta_db:+.2f} dB +/- {c.overall_uncertainty_db:.2f} "
                 f"({'significant' if c.overall_significant else 'not significant'}, {c.repeatability} repeatability)",
                 f"comparable: {'yes' if c.comparable else 'NO'}"]
        lines += [f"  [{i.effect}] {i.message}" for i in c.issues]
        lines += [f"  tone {t.freq_hz:.1f} Hz: {t.status} ({t.delta_db:+.1f} dB)" for t in c.tone_deltas if t.delta_db is not None]
        _print(args, dump_dict(c), "\n".join(lines))
    finally:
        app.close_case()


def cmd_align(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        r = app.align_captures(args.ref, args.other, args.ref_channel, args.other_channel)
        m = r["mapping"]
        lines = [f"mapping {m.id}: offset {m.offset_s * 1000:.3f} ms, drift {m.drift_ppm:+.2f} ppm, timing sigma {m.residual_s * 1e6:.1f} us, "
                 f"ambiguity {m.ambiguity_ratio:.2f}",
                 f"synchronized analysis allowed below {m.eligible_max_freq_hz:.0f} Hz" if m.eligible_max_freq_hz > 0 else
                 "synchronized analysis NOT allowed: use independent spectral comparison only"]
        lines += [f"  [{f.severity.value}] {f.message}" for f in r["flags"]]
        if r["coherent"]:
            lines.append(f"coherent components (gamma^2 > {r['threshold']:.2f}, {r['n_averages']} averages): " +
                         ", ".join(f"{fq:.1f} Hz ({c:.2f})" for fq, c in r["coherent"]))
        _print(args, {"mapping": dump_dict(m), "flags": [dump_dict(f) for f in r["flags"]], "coherent": r["coherent"]}, "\n".join(lines))
    finally:
        app.close_case()


def cmd_diagnose(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        s = app.diagnose()
        lines = [f"Conclusion: {s.conclusion.replace('_', ' ')} (ruleset {s.ruleset_version})"]
        lines += [f"  ! {r}" for r in s.abstention_reasons]
        lines.append("Hypotheses:")
        for h in s.hypotheses:
            lines.append(f"  [{h.level.value:<18}] {h.statement}")
            if args.verbose:
                lines += [f"      - {x}" for x in h.explanation]
        lines.append("Next tests:")
        for t in s.next_tests:
            lines.append(f"  * {t.title} {t.params or ''}{'' if t.available else ' (unavailable: ' + t.unavailable_reason + ')'}: {t.reason}")
        if args.verbose:
            lines.append("Evidence:")
            lines += [f"  ({e.statement_class.value}) {e.summary}{'' if e.valid else ' [not usable]'}" for e in s.evidence]
        _print(args, dump_dict(s), "\n".join(lines))
    finally:
        app.close_case()


def cmd_procedure(args):
    if args.action == "list":
        lib = procedures.library()
        print("\n".join(f"{d.id:<26} tier>={d.min_tier}  {d.title}" for d in lib.values()))
        return
    app = _app(args)
    app.open_case(args.case)
    try:
        if args.action == "start":
            run = app.start_procedure(args.procedure, _kv(args.param))
            print(run.id)
        else:
            run = app.run(args.run) if args.run else next((r for r in reversed(app.runs()) if r.state in ("running", "paused")), None)
            if run is None:
                raise ValidationError("no active procedure run; start one first")
            if args.action in ("pause", "resume", "cancel"):
                run = app.procedure_action(run.id, args.action)
            elif args.action == "step":
                step, rep = procedures.current(run)
                if step is None or run.state != "running":
                    print(f"run {run.id} is {run.state}")
                    return
                print(f"Step: {step.title} ({step.kind}) {'repeat ' + str(rep + 1) + '/' + str(step.repeats) if step.kind == 'capture' else ''}")
                print(f"  {step.instruction}")
                if step.kind == "instruction":
                    run = app.procedure_action(run.id, "ack")
                elif step.kind == "intervention":
                    if not args.description:
                        raise ValidationError("this step needs --description and the --changes flags")
                    rec = InterventionRecord(description=args.description, target=run.params.get("target", run.params.get("object", "")),
                                             changes_source_output="source" in (args.changes or []),
                                             changes_transmission_path="path" in (args.changes or []),
                                             changes_receiver="receiver" in (args.changes or []),
                                             changes_measurement_setup="setup" in (args.changes or []))
                    run = app.procedure_action(run.id, "intervention", record=rec)
                else:
                    if step.stimulus is not None:
                        if not args.confirm_output:
                            raise ValidationError("this step plays a test signal; add --confirm-output to arm the output")
                        app.arm_output(args.output_device, backend=args.backend, level_limit_dbfs=-12, confirmed=True,
                                       samplerate=args.rate, max_duration_s=step.duration_s + 2,
                                       active_input_device=args.device, allow_same_device=args.backend == "simulated")
                    if step.settle_s and args.backend != "simulated":
                        print(f"  settling {step.settle_s:g} s ...")
                        time.sleep(step.settle_s)
                    base = _spec(args, app)
                    run, m, failed = app.run_step_capture(run.id, base)
                    print(f"  capture {m.id if m else '-'}: {'ACCEPTED' if not failed else 'REJECTED: ' + '; '.join(failed)}")
            p, n = procedures.progress(run)
            print(f"run {run.id}: {run.state} (step {p}/{n}){' outcome: ' + run.outcome if run.outcome else ''}")
    finally:
        app.close_case()


def cmd_calibrate(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        if args.file:
            prof = app.calibration_from_file(args.sensor, Path(args.file), args.kind, args.sensitivity, gain_db=args.gain)
        else:
            prof = app.calibrate_from_capture(args.capture, args.channel, args.ref_level, args.ref_freq)
        _print(args, dump_dict(prof), f"calibration {prof.id}: sensitivity {prof.sensitivity_fs_per_unit:.5g} FS/{prof.quantity.value} "
                                      f"(+/-{prof.uncertainty_db:.2f} dB, valid {prof.valid_band_hz[0]:g}-{prof.valid_band_hz[1]:g} Hz)")
    finally:
        app.close_case()


def cmd_report(args):
    app = _app(args)
    app.open_case(args.case)
    try:
        if args.diagnose:
            app.diagnose()
        p = app.export_report(args.format, Path(args.out) if args.out else None, tuple(args.redact or ()))
        _print(args, {"path": str(p)}, f"report written to {p}")
    finally:
        app.close_case()


def cmd_archive(args):
    app = _app(args)
    if args.action == "export":
        app.open_case(args.case)
        try:
            p = app.export_archive(Path(args.path), include_derived=not args.no_derived)
            _print(args, {"path": str(p)}, f"archive written to {p}")
        finally:
            app.close_case()
    else:
        cid = app.import_archive(Path(args.path))
        _print(args, {"case_id": cid}, f"imported case {cid}")


def cmd_stimulus(args):
    app = _app(args)
    if not args.confirm:
        raise ValidationError("playing a test signal requires --confirm (check the volume first)")
    app.arm_output(args.device, backend=args.backend, level_limit_dbfs=args.limit, max_duration_s=args.duration, confirmed=True,
                   samplerate=args.rate)
    params = {"freq": args.freq, "f0": args.f0, "f1": args.f1}
    eff = app.output.play(StimulusRecord(kind=args.type, level_dbfs=args.level, params=params), args.duration)
    print(f"playing {eff.kind} at {eff.level_dbfs:.1f} dBFS peak for {args.duration:g} s (Ctrl+C stops)")
    try:
        app.output.wait(args.duration + 3)
    except KeyboardInterrupt:
        app.output.stop()
    print("output disarmed")


def cmd_qualify(args):
    app = _app(args)
    rec = app.run_loopback(args.backend, args.output_device, args.input_device, args.rate)
    _print(args, rec, f"{rec['device']}: {rec['status']}\n" + "\n".join(f"  {k}: {v}" for k, v in rec["results"].items()))


def cmd_demo(args):
    from ..app.demo import run_demo

    app = _app(args)
    cid = run_demo(app, progress=print, duration_scale=args.scale)
    p = app.export_report("html")
    print(f"demo case {cid}; report {p}")
    app.shutdown()


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sonicclue-cli", description="SonicClue: sound and vibration cause investigation")
    ap.add_argument("--version", action="version", version=f"SonicClue {__version__} (build {BUILD_ID})")
    ap.add_argument("--workspace", help="workspace folder (default: Documents/SonicClue or $SONICCLUE_WORKSPACE)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--sim-speed", type=float, default=1.0, help="simulator speed factor (simulated backend only)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def dev(p, duration=True):
        p.add_argument("--backend", default="portaudio", choices=["portaudio", "simulated"])
        p.add_argument("--device", type=int)
        p.add_argument("--rate", type=float, default=48000.0)
        p.add_argument("--exclusive", action="store_true", help="WASAPI exclusive mode")
        p.add_argument("--ch", action="append", help="channel 'idx:label[:sensor[:position[:mounting[:gain_db[:agc[:calibration]]]]]]'")
        if duration:
            p.add_argument("--duration", type=float, default=15.0)

    sub.add_parser("info").set_defaults(fn=cmd_info)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    p = sub.add_parser("devices")
    p.add_argument("--backend", default="portaudio", choices=["portaudio", "simulated"])
    p.set_defaults(fn=cmd_devices)

    p = sub.add_parser("case")
    p.add_argument("action", choices=["list", "new", "show", "verify", "annotate", "history"])
    p.add_argument("--case")
    p.add_argument("--title", default="New investigation")
    p.add_argument("--summary")
    p.add_argument("--receiver")
    p.add_argument("--character", action="append", choices=["hum", "buzz", "rattle", "whine", "rumble", "tonal", "broadband",
                                                            "intermittent", "continuous", "felt_vibration"])
    p.add_argument("--equipment", action="append", help="id=Name:kind")
    p.add_argument("--sensor", action="append", help="id=kind (e.g. mic1=studio_mic)")
    p.add_argument("--target")
    p.add_argument("--text")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(fn=cmd_case)

    p = sub.add_parser("capture")
    p.add_argument("--case", required=True)
    dev(p)
    p.add_argument("--label")
    p.add_argument("--state", action="append", help="equipment state id=on|off")
    p.add_argument("--analyze", action="store_true")
    p.set_defaults(fn=cmd_capture)

    p = sub.add_parser("import")
    p.add_argument("--case", required=True)
    p.add_argument("file")
    p.add_argument("--bridge", action="store_true", help="file is a raw sensor-bridge serial dump")
    p.add_argument("--sensor")
    p.add_argument("--ch", action="append")
    p.add_argument("--label")
    p.add_argument("--state", action="append")
    p.add_argument("--analyze", action="store_true")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("analyze")
    p.add_argument("--case", required=True)
    p.add_argument("--capture", action="append")
    p.add_argument("--resolution", type=float)
    p.add_argument("--window", choices=["hann", "hamming", "blackmanharris", "flattop", "boxcar"])
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("compare")
    p.add_argument("--case", required=True)
    p.add_argument("--a", action="append", required=True)
    p.add_argument("--b", action="append", required=True)
    p.add_argument("--channel", required=True)
    p.add_argument("--label-a", default="A")
    p.add_argument("--label-b", default="B")
    p.add_argument("--band", type=float, nargs=2)
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("align", help="estimate clock mapping between two independently clocked captures")
    p.add_argument("--case", required=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--other", required=True)
    p.add_argument("--ref-channel", required=True)
    p.add_argument("--other-channel", required=True)
    p.set_defaults(fn=cmd_align)

    p = sub.add_parser("diagnose")
    p.add_argument("--case", required=True)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_diagnose)

    p = sub.add_parser("procedure")
    p.add_argument("action", choices=["list", "start", "step", "pause", "resume", "cancel"])
    p.add_argument("--case")
    p.add_argument("--procedure")
    p.add_argument("--param", action="append", help="target=<equipment id> or object=<name>")
    p.add_argument("--run")
    p.add_argument("--description")
    p.add_argument("--changes", action="append", choices=["source", "path", "receiver", "setup"])
    p.add_argument("--confirm-output", action="store_true")
    p.add_argument("--output-device", type=int)
    dev(p)
    p.set_defaults(fn=cmd_procedure)

    p = sub.add_parser("calibrate")
    p.add_argument("--case", required=True)
    p.add_argument("--capture")
    p.add_argument("--channel")
    p.add_argument("--ref-level", type=float, default=94.0, help="dB SPL (sound) or RMS m/s^2 (acceleration)")
    p.add_argument("--ref-freq", type=float, default=1000.0)
    p.add_argument("--file", help="frequency-response file")
    p.add_argument("--kind", choices=["response", "correction"], default="response")
    p.add_argument("--sensor")
    p.add_argument("--sensitivity", type=float)
    p.add_argument("--gain", type=float)
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("report")
    p.add_argument("--case", required=True)
    p.add_argument("--format", choices=["html", "pdf", "json", "csv"], default="html")
    p.add_argument("--out")
    p.add_argument("--redact", action="append", choices=["names", "locations", "serials", "notes"])
    p.add_argument("--diagnose", action="store_true", help="recompute the diagnosis first")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("archive")
    p.add_argument("action", choices=["export", "import"])
    p.add_argument("path")
    p.add_argument("--case")
    p.add_argument("--no-derived", action="store_true")
    p.set_defaults(fn=cmd_archive)

    p = sub.add_parser("stimulus")
    p.add_argument("--type", choices=["sine", "sweep", "white", "pink", "band_noise", "impulse"], default="sine")
    p.add_argument("--freq", type=float, default=1000.0)
    p.add_argument("--f0", type=float, default=20.0)
    p.add_argument("--f1", type=float, default=20000.0)
    p.add_argument("--level", type=float, default=-30.0, help="peak dBFS")
    p.add_argument("--limit", type=float, default=-20.0)
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--backend", default="portaudio", choices=["portaudio", "simulated"])
    p.add_argument("--device", type=int)
    p.add_argument("--rate", type=float, default=48000.0)
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(fn=cmd_stimulus)

    p = sub.add_parser("qualify", help="loopback hardware qualification (output cabled to input)")
    p.add_argument("--backend", default="portaudio", choices=["portaudio", "simulated"])
    p.add_argument("--output-device", type=int, required=True)
    p.add_argument("--input-device", type=int, required=True)
    p.add_argument("--rate", type=float, default=48000.0)
    p.set_defaults(fn=cmd_qualify)

    p = sub.add_parser("demo", help="run a complete SIMULATED investigation")
    p.add_argument("--scale", type=float, default=1.0, help="capture duration scale")
    p.set_defaults(fn=cmd_demo)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        rc = args.fn(args)
        return int(rc or 0)
    except KeyboardInterrupt:
        return 130
    except ValidationError as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    except SonicClueError as exc:
        print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
        return 3 if exc.code in ("SC_INTEGRITY",) else 2
    except Exception as exc:  # noqa: BLE001
        from pydantic import ValidationError as PVE

        if isinstance(exc, PVE):
            print(f"error [SC_VALIDATION]: {exc.errors()[0]['loc']}: {exc.errors()[0]['msg']}", file=sys.stderr)
            return 1
        print(f"error [SC_INTERNAL]: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

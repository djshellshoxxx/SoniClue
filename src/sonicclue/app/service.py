"""Application service facade (docs/specs/03 section 5, 04 section 4).

``SonicClueApp`` is the one entry point used by both the GUI and the CLI, so
both modes run the same measurement and evidence engine. It owns the
workspace, the open case store, the audio backends, the output controller,
the job runner and the settings.

Thread rules: methods may be called from the GUI thread or a job thread.
CaseStore is thread-safe. Live capture runs in its own session threads.
``CaptureHandle.finalize()`` must be called exactly once (it is idempotent)
from any thread after the session reaches a terminal state.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import BUILD_ID, __version__, procedures
from ..acquisition import importer
from ..acquisition.backends import PortAudioBackend, SimulatedBackend, SimWorld
from ..acquisition.session import CaptureSession, SessionState
from ..analysis.pipeline import analyze as run_analysis
from ..analysis.spool import ChannelSpool
from ..compare import comparability
from ..compare.compare import Item, compare as run_compare
from ..diagnostics import CaptureView, DiagnosticInputs, diagnose as run_diagnose
from ..domain.errors import CalibrationError, StateError, StorageError, ValidationError
from ..domain.model import (
    VIBRATION_KINDS,
    ACOUSTIC_KINDS,
    AnalysisConfig,
    Annotation,
    CalibrationProfile,
    CaptureContext,
    CaptureManifest,
    ChannelConfig,
    DeviceInfo,
    Equipment,
    ProblemDescription,
    ProcedureRun,
    QualityCode,
    QualityFlag,
    SensorDescriptor,
    Severity,
    StimulusRecord,
    dump_json,
    utcnow,
)
from ..qualification import QualificationMatrix, loopback_test, selftest
from ..reporting import render
from ..reporting.builder import ReportInputs, build_report
from ..sensors import calibration as cal
from ..stimulus import OutputController
from ..storage.archive import export_case, import_case
from ..storage.files import atomic_write_text, make_readonly, sha256_file
from ..storage.store import CaseStore, Workspace, new_id
from .jobs import JobRunner

# Captures longer than SPOOL_ABOVE_S are analysed from a disk spool (bounded memory);
# MAX_ANALYSIS_S matches the 4 h live-capture limit (spec 16).
SPOOL_ABOVE_S = 600
MAX_ANALYSIS_S = 4 * 3600
ALIGN_MAX_S = 1800  # clock alignment reads at most the first 30 min of each capture (offset + drift are well determined; bounds float64 memory)

DEFAULT_SETTINGS = {"mode": "guided", "backend": "portaudio", "device": None, "samplerate": 48000, "output_device": None,
                    "analysis": {}, "auto_analyze": True, "max_analysis_seconds": MAX_ANALYSIS_S}


def default_workspace() -> Path:
    env = os.environ.get("SONICCLUE_WORKSPACE")
    if env:
        return Path(env)
    base = Path(os.environ.get("USERPROFILE") or Path.home())
    docs = base / "Documents"
    return (docs if docs.exists() else base) / "SonicClue"


@dataclass
class CaptureSpec:
    channels: list[ChannelConfig]
    duration_s: float
    context: CaptureContext = field(default_factory=CaptureContext)
    backend: str = "portaudio"
    device: int | None = None
    samplerate: float = 48000.0
    exclusive: bool = False
    stimulus: StimulusRecord | None = None  # requires the output to be armed beforehand
    output_device: int | None = None


class CaptureHandle:
    def __init__(self, app: "SonicClueApp", store: CaseStore, session: CaptureSession, capture_id: str, spec: CaptureSpec,
                 device: DeviceInfo, source: str):
        self.app, self.store, self.session, self.id, self.spec = app, store, session, capture_id, spec
        self.device, self.source = device, source
        self.manifest: CaptureManifest | None = None
        self.stimulus_played: StimulusRecord | None = None
        self._finalized = False

    @property
    def state(self) -> SessionState:
        return self.session.state

    def stop(self) -> None:
        self.session.stop()
        self.app.output.stop()

    def cancel(self) -> None:
        self.session.cancel()
        self.app.output.stop()

    def finalize(self, timeout: float | None = None) -> CaptureManifest | None:
        """Wait for the session and persist the manifest (or discard on cancel)."""
        if self._finalized:
            return self.manifest
        oc = self.session.wait(timeout)
        self.app.output.stop()
        self._finalized = True
        cdir = self.store.capture_dir(self.id)
        if oc.state is SessionState.CANCELLED:
            for f in cdir.rglob("*"):
                try:
                    os.chmod(f, 0o666)
                except OSError:
                    pass
            shutil.rmtree(cdir, ignore_errors=True)
            self.store.audit("capture.cancel", self.id, "discarded by user")
            return None
        if oc.frames == 0:
            shutil.rmtree(cdir, ignore_errors=True)
            raise StorageError(f"capture produced no data: {oc.error or 'unknown error'}", code="SC_CAPTURE_EMPTY")
        flags = list(oc.flags)
        if self.source == "simulated":
            flags.insert(0, QualityFlag(code=QualityCode.SIMULATED_DATA, severity=Severity.WARNING,
                                        message="SIMULATED data from the built-in simulator; not a physical measurement"))
        status = "partial" if oc.state is SessionState.FAILED else "complete"
        if status == "partial":
            flags.append(QualityFlag(code=QualityCode.PARTIAL_CAPTURE, severity=Severity.WARNING,
                                     message="capture ended early; data up to the failure is kept"))
        self.manifest = self.app._build_manifest(self.id, self.store, self.spec, self.device, self.source, oc.frames,
                                                 oc.chunks, oc.gaps, flags, status, self.stimulus_played)
        self.store.save_capture(self.manifest)
        return self.manifest


class SonicClueApp:
    def __init__(self, workspace: Path | None = None, *, sim_world: SimWorld | None = None, sim_speed: float = 1.0):
        self.workspace = Workspace(workspace or default_workspace())
        self.settings = self._load_settings()
        self.store: CaseStore | None = None
        self.sim = SimulatedBackend(sim_world, speed=sim_speed)
        self._pa: PortAudioBackend | None = None
        self._pa_error: str | None = None
        self.output = OutputController(self.backend(self.settings.get("backend", "portaudio")) if self._backend_ok() else self.sim)
        self.jobs = JobRunner()
        self.qualification = QualificationMatrix(self.workspace.root / "qualification.json")
        (self.workspace.root / "calibrations").mkdir(exist_ok=True)

    # ---------------- settings ----------------
    def _load_settings(self) -> dict:
        p = self.workspace.root / "settings.json"
        s = dict(DEFAULT_SETTINGS)
        if p.exists():
            try:
                s.update(json.loads(p.read_text()))
            except (OSError, ValueError):
                pass
        return s

    def save_settings(self, **changes) -> dict:
        if "analysis" in changes:
            AnalysisConfig(**changes["analysis"])  # validate
        self.settings.update(changes)
        atomic_write_text(self.workspace.root / "settings.json", json.dumps(self.settings, indent=1))
        return self.settings

    def analysis_config(self) -> AnalysisConfig:
        return AnalysisConfig(**self.settings.get("analysis", {}))

    # ---------------- backends ----------------
    def _backend_ok(self) -> bool:
        try:
            self.backend("portaudio")
            return True
        except Exception:  # noqa: BLE001
            return False

    def backend(self, name: str):
        if name == "simulated":
            return self.sim
        if name != "portaudio":
            raise ValidationError(f"unknown backend {name}")
        if self._pa is None:
            if self._pa_error:
                from ..domain.errors import DeviceError

                raise DeviceError(self._pa_error, code="SC_NO_AUDIO_BACKEND")
            try:
                self._pa = PortAudioBackend()
            except Exception as exc:  # noqa: BLE001
                self._pa_error = str(exc)
                raise
        return self._pa

    def devices(self, backend: str = "portaudio"):
        return self.backend(backend).list_devices()

    # ---------------- cases ----------------
    def list_cases(self) -> list[dict]:
        return self.workspace.list_cases()

    def create_case(self, title: str, problem: ProblemDescription | None = None, equipment: list[Equipment] | None = None,
                    sensors: list[SensorDescriptor] | None = None, open_it: bool = True) -> str:
        st = self.workspace.create_case(title, problem=problem or ProblemDescription(), equipment=equipment or [],
                                        sensors=sensors or [])
        cid = st.case.id
        if open_it:
            self.close_case()
            self.store = st
        else:
            st.close()
        return cid

    def open_case(self, case_id: str) -> CaseStore:
        self.close_case()
        self.store = self.workspace.open_case(case_id)
        return self.store

    def close_case(self) -> None:
        if self.store is not None:
            self.jobs.cancel_all()  # no job may touch the case after it is closed
            self.store.close()
            self.store = None

    def delete_case(self, case_id: str) -> None:
        if self.store and self.store.case.id == case_id:
            self.close_case()
        self.workspace.delete_case(case_id)

    def _s(self) -> CaseStore:
        if self.store is None:
            raise StateError("no case is open", code="SC_NO_CASE")
        return self.store

    def case(self):
        return self._s().case

    def update_problem(self, problem: ProblemDescription):
        return self._s().update_case(problem=problem)

    def set_equipment(self, equipment: list[Equipment]):
        ids = [e.id for e in equipment]
        if len(set(ids)) != len(ids):
            raise ValidationError("duplicate equipment id")
        return self._s().update_case(equipment=equipment)

    def add_equipment(self, eq: Equipment):
        cur = [e for e in self.case().equipment if e.id != eq.id]
        return self.set_equipment(cur + [eq])

    def set_sensors(self, sensors: list[SensorDescriptor]):
        return self._s().update_case(sensors=sensors)

    def add_sensor(self, s: SensorDescriptor):
        return self.set_sensors([x for x in self.case().sensors if x.id != s.id] + [s])

    def annotate(self, target: str, text: str) -> Annotation:
        a = Annotation(id=new_id("note"), case_id=self.case().id, target=target, text=text, created_utc=utcnow())
        self._s().put("annotation", a, parent=target)
        return a

    # ---------------- captures ----------------
    def _build_manifest(self, cid, store, spec: CaptureSpec, device: DeviceInfo, source, frames, chunks, gaps, flags, status,
                        stimulus) -> CaptureManifest:
        return CaptureManifest(id=cid, case_id=store.case.id, created_utc=utcnow(), source=source, device=device,
                               sample_rate_hz=spec.samplerate, channels=spec.channels, frames=frames, chunks=chunks, gaps=gaps,
                               quality=flags, clock_domain=f"{device.backend}:{device.name}:{cid}", status=status,
                               context=spec.context, stimulus=stimulus, software_version=f"{__version__}+{BUILD_ID}")

    def _validate_channels(self, channels: list[ChannelConfig]) -> None:
        case = self.case()
        sids = {s.id for s in case.sensors}
        for ch in channels:
            if ch.sensor_id and ch.sensor_id not in sids:
                raise ValidationError(f"channel {ch.label}: sensor {ch.sensor_id} is not defined in this case")
            if ch.calibration_id and self._s().get("calibration", ch.calibration_id) is None:
                raise ValidationError(f"channel {ch.label}: calibration {ch.calibration_id} not found in this case")
        labels = [c.label for c in channels]
        if len(set(labels)) != len(labels):
            raise ValidationError("channel labels must be unique")

    def start_capture(self, spec: CaptureSpec) -> CaptureHandle:
        store = self._s()
        self._validate_channels(spec.channels)
        if spec.duration_s <= 0 or spec.duration_s > 4 * 3600:
            raise ValidationError("duration must be between 0 and 4 hours")
        be = self.backend(spec.backend)
        dev = spec.device if spec.device is not None else (0 if spec.backend == "simulated" else self.settings.get("device"))
        if dev is None:
            raise ValidationError("no input device selected", code="SC_NO_DEVICE")
        nch = max(c.index for c in spec.channels) + 1
        if spec.backend == "simulated":
            self.sim.world.state.update(spec.context.equipment_state)
            pos = next((c.placement.position_id for c in spec.channels if c.placement.position_id), "")
            self.sim.world.mic_position = pos or "P1"
            self.sim.world.contact_mounted = all(c.placement.mounting.value != "resting" for c in spec.channels if c.index == 1)
        descs = {d.index: d for d in be.list_devices()}
        if dev not in descs:
            raise ValidationError(f"device {dev} not found", code="SC_NO_DEVICE")
        d = descs[dev]
        info = DeviceInfo(backend="simulated" if spec.backend == "simulated" else "portaudio", host_api=d.host_api, name=d.name,
                          device_index=dev, exclusive_mode=spec.exclusive)
        cid = new_id("cap")
        writer = store.new_capture_writer(cid, spec.samplerate, nch, header={})
        sess = CaptureSession(be, dev, spec.samplerate, nch, writer, duration_s=spec.duration_s, exclusive=spec.exclusive)
        handle = CaptureHandle(self, store, sess, cid, spec, info, "simulated" if spec.backend == "simulated" else "live")
        # journal header: everything needed to rebuild the manifest after a crash
        hdr = json.loads(dump_json(self._build_manifest(cid, store, spec, info, handle.source, 0, [], [], [], "complete", spec.stimulus)))
        for k in ("frames", "chunks", "status"):
            hdr.pop(k, None)
        writer.header = hdr
        writer._journal()
        try:
            sess.start()
        except Exception:
            shutil.rmtree(store.capture_dir(cid), ignore_errors=True)
            raise
        if spec.stimulus is not None:
            try:
                handle.stimulus_played = self.output.play(spec.stimulus, spec.duration_s)
            except BaseException:
                sess.cancel()
                try:
                    sess.wait(timeout=15)
                except Exception:  # noqa: BLE001
                    pass
                shutil.rmtree(store.capture_dir(cid), ignore_errors=True)
                raise
        return handle

    def capture_blocking(self, spec: CaptureSpec, timeout_extra: float = 30.0) -> CaptureManifest | None:
        h = self.start_capture(spec)
        return h.finalize(timeout=spec.duration_s * 2 + timeout_extra)

    def import_audio(self, path: Path, channels: list[ChannelConfig] | None = None, context: CaptureContext | None = None) -> CaptureManifest:
        store = self._s()
        info = importer.probe(path)
        chans = channels or [ChannelConfig(index=i, label=f"ch{i + 1}") for i in range(info["channels"])]
        if len(chans) != info["channels"]:
            raise ValidationError(f"file has {info['channels']} channels but {len(chans)} channel descriptions were given")
        self._validate_channels(chans)
        cid = new_id("cap")
        w = store.new_capture_writer(cid, info["samplerate"], info["channels"], header={})
        try:
            return self._finish_audio_import(store, cid, w, path, info, chans, context)
        except BaseException:
            shutil.rmtree(store.capture_dir(cid), ignore_errors=True)
            raise

    def _finish_audio_import(self, store, cid, w, path, info, chans, context) -> CaptureManifest:
        frames = importer.import_audio(path, w)
        dst = store.capture_dir(cid) / f"original{Path(path).suffix.lower()}"
        shutil.copy2(path, dst)
        make_readonly(dst)
        digest = sha256_file(dst)
        flags = []
        if info["lossy"]:
            flags.append(QualityFlag(code=QualityCode.ALIAS_RISK, severity=Severity.WARNING,
                                     message="lossy-compressed source: codec artifacts can create or remove spectral detail"))
        ctx = (context or CaptureContext())
        ctx = ctx.model_copy(update={"notes": (ctx.notes + "\n" if ctx.notes else "") +
                                     f"imported from {Path(path).name} ({info['format']}/{info['subtype']}), sha256 {digest}"})
        spec = CaptureSpec(channels=chans, duration_s=max(frames / info["samplerate"], 1e-6), context=ctx, samplerate=info["samplerate"])
        dev = DeviceInfo(backend="file", name=Path(path).name)
        m = self._build_manifest(cid, store, spec, dev, "import", frames, w.chunks, [], flags, "complete", None)
        store.save_capture(m)
        return m

    def import_bridge(self, path: Path, sensor_id: str | None = None, context: CaptureContext | None = None) -> CaptureManifest:
        store = self._s()
        asm = importer.decode_bridge_dump(path)
        h = asm.hello
        axes = asm.samples.shape[1]
        chans = [ChannelConfig(index=i, label=("accel" if axes == 1 else "xyz"[i] if i < 3 else f"a{i}"), sensor_id=sensor_id, agc="off")
                 for i in range(axes)]
        self._validate_channels(chans)
        cid = new_id("cap")
        w = store.new_capture_writer(cid, h.sample_rate_hz, axes, header={})
        try:
            return self._finish_bridge_import(store, cid, w, asm, chans, context)
        except BaseException:
            shutil.rmtree(store.capture_dir(cid), ignore_errors=True)
            raise

    def _finish_bridge_import(self, store, cid, w, asm, chans, context) -> CaptureManifest:
        h, _axes = asm.hello, asm.samples.shape[1]
        frames = importer.array_writer_feed(w, asm.samples)
        from ..domain.model import Gap

        gaps = [Gap(start_frame=a, end_frame=b, reason="dropout") for a, b in asm.gaps]
        spec = CaptureSpec(channels=chans, duration_s=frames / h.sample_rate_hz, context=context or CaptureContext(), samplerate=h.sample_rate_hz)
        dev = DeviceInfo(backend="bridge", name=f"{h.device_model} fw {h.firmware_version}")
        m = self._build_manifest(cid, store, spec, dev, "import", frames, w.chunks, gaps, asm.flags, "complete", None)
        store.save_capture(m)
        return m

    def captures(self) -> list[CaptureManifest]:
        return self._s().list("capture")

    def capture(self, cid: str) -> CaptureManifest:
        m = self._s().get("capture", cid)
        if m is None:
            raise ValidationError(f"capture {cid} not found", code="SC_NOT_FOUND")
        return m

    def capture_data(self, cid: str, start_s: float = 0.0, end_s: float | None = None) -> np.ndarray:
        m = self.capture(cid)
        a = int(start_s * m.sample_rate_hz)
        b = None if end_s is None else int(end_s * m.sample_rate_hz)
        return self._s().load_capture_data(m, a, b)

    # ---------------- analysis ----------------
    def analyze(self, cid: str, config: AnalysisConfig | None = None, cancel=None):
        store = self._s()
        m = self.capture(cid)
        maxf = int(self.settings.get("max_analysis_seconds", MAX_ANALYSIS_S) * m.sample_rate_hz)
        nf = min(m.frames, maxf)
        if m.frames > maxf:
            m = m.model_copy(update={"quality": list(m.quality) + [QualityFlag(
                code=QualityCode.PARTIAL_CAPTURE, severity=Severity.INFO,
                message=f"only the first {maxf / m.sample_rate_hz:.0f} s were analysed (max_analysis_seconds)")]})
        case = store.case
        cals = {c.id: c for c in store.list("calibration")}
        sensors = {s.id: s for s in case.sensors}
        cfg = config or self.analysis_config()
        if nf > SPOOL_ABOVE_S * m.sample_rate_hz:
            # long capture: disk-spooled channels keep resident memory bounded (spec 16 section 5)
            with ChannelSpool(lambda a, b: store.load_capture_data(m, a, b), nf, len(m.channels), store.path / "derived", cancel) as sp:
                out = run_analysis(m, sp, sensors, cals, cfg, cancel=cancel)
        else:
            out = run_analysis(m, store.load_capture_data(m, 0, nf), sensors, cals, cfg, cancel=cancel)
        return store.save_analysis(out.result, out.arrays)

    def analysis(self, cid: str, ensure: bool = True):
        a = self._s().latest_analysis(cid)
        if a is None and ensure:
            a = self.analyze(cid)
        return a

    def arrays(self, analysis) -> dict:
        return self._s().load_arrays(analysis)

    def _item(self, cid: str) -> Item:
        a = self.analysis(cid)
        return Item(self.capture(cid), a, self.arrays(a))

    def compare(self, captures_a: list[str], captures_b: list[str], channel_label: str, *, label_a: str = "A", label_b: str = "B",
                kind: str = "generic", run_id: str | None = None, band: tuple[float, float] | None = None):
        case = self.case()
        band = band or case.problem.approx_band_hz
        res = run_compare(case.id, [self._item(c) for c in captures_a], [self._item(c) for c in captures_b], channel_label,
                          label_a=label_a, label_b=label_b, kind=kind, run_id=run_id, band=band)
        self._s().put("comparison", res)
        self._s().audit("comparison.add", res.id, f"{label_a} vs {label_b} {res.overall_delta_db:+.1f} dB")
        return res

    def comparisons(self):
        return self._s().list("comparison")

    # ---------------- multi-device synchronization ----------------
    def align_captures(self, ref_id: str, other_id: str, ref_label: str, other_label: str) -> dict:
        """Estimate a clock mapping between two independently clocked captures (e.g. two
        interfaces recorded at the same time) and, where timing allows, compute
        coherence between the reference channel and the aligned other channel, limited
        to the eligible band. Stores the ClockMapping in the case."""
        from ..domain.model import ClockMapping  # noqa: F401
        from ..dsp import cross, spectral
        from ..sync import align, estimate_mapping

        mr, mo = self.capture(ref_id), self.capture(other_id)
        cr = [c.label for c in mr.channels].index(ref_label)
        co = [c.label for c in mo.channels].index(other_label)
        lim = min(float(self.settings.get("max_analysis_seconds", MAX_ANALYSIS_S)), ALIGN_MAX_S)
        xr = self.capture_data(ref_id, 0.0, lim)[:, cr].astype(float)
        xo = self.capture_data(other_id, 0.0, lim)[:, co].astype(float)
        mapping, flags, o_rs = estimate_mapping(xr, mr.sample_rate_hz, xo, mo.sample_rate_hz, ref_id=ref_id, other_id=other_id)
        self._s().put("clock_mapping", mapping, parent=ref_id)
        self._s().audit("sync.mapping", mapping.id, f"{ref_id}<-{other_id} offset {mapping.offset_s:.6f}s drift {mapping.drift_ppm:.1f}ppm")
        out = {"mapping": mapping, "flags": flags, "coherent": [], "n_averages": 0, "threshold": 1.0}
        if mapping.eligible_max_freq_hz <= 0:
            return out
        al, valid = align(o_rs, mapping, mr.sample_rate_hz, len(xr))
        plan = spectral.plan_segments(valid, mr.sample_rate_hz, 2.0, 0.5, 8)
        if plan is None or not plan.sufficient:
            out["flags"] = flags + [QualityFlag(code=QualityCode.INSUFFICIENT_AVERAGES, severity=Severity.WARNING,
                                                message="aligned overlap too short for coherence")]
            return out
        f, pxx, pyy, pxy = spectral.masked_csd(xr, al, mr.sample_rate_hz, plan)
        coh, h1, ok = cross.coherence_and_transfer(pxx, pyy, pxy)
        thr = max(cross.coherence_threshold(plan.n_eff, 0.05), 0.5)
        sel = ok & (f > 0) & (f <= mapping.eligible_max_freq_hz) & (coh > thr)
        idx = np.flatnonzero(sel)
        if len(idx):
            top = idx[np.argsort(coh[idx])[::-1][:15]]
            out["coherent"] = [(float(f[k]), float(coh[k])) for k in sorted(top)]
        out["n_averages"], out["threshold"] = plan.n_eff, thr
        return out

    # ---------------- diagnosis ----------------
    def diagnostic_inputs(self) -> DiagnosticInputs:
        st = self._s()
        views = [CaptureView(m, st.latest_analysis(m.id)) for m in st.list("capture")]
        return DiagnosticInputs(case=st.case, captures=views, comparisons=st.list("comparison"), runs=st.list("procedure_run"))

    def diagnose(self):
        snap = run_diagnose(self.diagnostic_inputs())
        self._s().put("diagnosis", snap)
        self._s().audit("diagnosis.add", snap.id, snap.conclusion)
        return snap

    def latest_diagnosis(self):
        d = self._s().list("diagnosis")
        return d[-1] if d else None

    def diagnoses(self):
        return self._s().list("diagnosis")

    # ---------------- calibration ----------------
    def calibrations(self) -> list[CalibrationProfile]:
        return self._s().list("calibration")

    def add_calibration(self, prof: CalibrationProfile, to_library: bool = True) -> CalibrationProfile:
        self._s().put("calibration", prof)
        self._s().audit("calibration.add", prof.id, f"{prof.method} sensor {prof.sensor_id}")
        if to_library:
            atomic_write_text(self.workspace.root / "calibrations" / f"{prof.id}.json", dump_json(prof))
        return prof

    def library_calibrations(self) -> list[CalibrationProfile]:
        out = []
        for p in sorted((self.workspace.root / "calibrations").glob("*.json")):
            try:
                out.append(CalibrationProfile.model_validate_json(p.read_text()))
            except Exception:  # noqa: BLE001
                continue
        return out

    def calibrate_from_capture(self, cid: str, channel_label: str, reference_level: float, reference_freq_hz: float, *,
                               calibrator_uncertainty_db: float = 0.4) -> CalibrationProfile:
        m = self.capture(cid)
        ch = next((c for c in m.channels if c.label == channel_label), None)
        if ch is None or not ch.sensor_id:
            raise CalibrationError("choose a channel with an assigned sensor")
        sensor = next(s for s in self.case().sensors if s.id == ch.sensor_id)
        col = [c.index for c in m.channels].index(ch.index)
        x = self._s().load_capture_data(m)[:, col].astype(np.float64)
        prof = cal.calibrate_from_tone(x, m.sample_rate_hz, sensor, reference_level, reference_freq_hz, gain_db=ch.input_gain_db,
                                       device_name=m.device.name, capture_id=cid, calibrator_uncertainty_db=calibrator_uncertainty_db)
        return self.add_calibration(prof)

    def calibration_from_file(self, sensor_id: str, path: Path, kind: str, sensitivity_fs_per_unit: float | None = None, *,
                              gain_db: float | None = None, uncertainty_db: float = 1.5) -> CalibrationProfile:
        sensor = next((s for s in self.case().sensors if s.id == sensor_id), None)
        if sensor is None:
            raise CalibrationError(f"sensor {sensor_id} not in case")
        if sensor.kind.value in ("contact_pickup", "piezo_disc", "line_input"):
            raise CalibrationError(f"{sensor.kind.value} sensors cannot be calibrated", code="SC_CAL_RELATIVE_ONLY")
        pts, sens_db = cal.parse_fr_file(Path(path).read_text(errors="replace"), kind)
        if sensitivity_fs_per_unit is None:
            raise CalibrationError("a sensitivity (from a calibrator recording or datasheet) is required in addition to the response file")
        prof = CalibrationProfile(id=f"cal-{uuid.uuid4().hex[:10]}", sensor_id=sensor_id, quantity=sensor.quantity,
                                  sensitivity_fs_per_unit=sensitivity_fs_per_unit, reference_freq_hz=1000.0, reference_gain_db=gain_db,
                                  fr_correction=pts, valid_band_hz=(pts[0].freq_hz, pts[-1].freq_hz), uncertainty_db=uncertainty_db,
                                  method="manufacturer_sheet", created_utc=utcnow(),
                                  notes=f"response file {Path(path).name} ({kind})" + (f", Sens Factor {sens_db} dB" if sens_db is not None else ""))
        return self.add_calibration(prof)

    # ---------------- procedures ----------------
    def runs(self) -> list[ProcedureRun]:
        return self._s().list("procedure_run")

    def run(self, run_id: str) -> ProcedureRun:
        r = self._s().get("procedure_run", run_id)
        if r is None:
            raise ValidationError(f"procedure run {run_id} not found", code="SC_NOT_FOUND")
        return r

    def _save_run(self, run: ProcedureRun) -> ProcedureRun:
        self._s().put("procedure_run", run, parent=run.case_id)
        return run

    def start_procedure(self, proc_id: str, params: dict[str, str] | None = None) -> ProcedureRun:
        d = procedures.get(proc_id)
        case = self.case()
        for k in ("target",):
            if k in d.parameters and params and params.get(k) not in case.equipment_ids():
                raise ValidationError(f"target '{params.get(k)}' is not equipment of this case")
        run = procedures.start(case.id, d, params or {})
        self._s().audit("procedure.start", run.id, proc_id)
        return self._save_run(run)

    def procedure_action(self, run_id: str, action: str, **kw) -> ProcedureRun:
        run = self.run(run_id)
        fn = {"ack": procedures.acknowledge, "pause": procedures.pause, "resume": procedures.resume,
              "cancel": procedures.cancel}.get(action)
        if action == "intervention":
            run = procedures.record_intervention(run, kw["record"])
        elif action == "fail":
            run = procedures.fail(run, kw.get("reason", "failed"))
        elif fn:
            run = fn(run)
        else:
            raise ValidationError(f"unknown action {action}")
        self._save_run(run)
        self._s().audit(f"procedure.{action}", run.id, run.state)
        if run.state == "completed":
            self._procedure_complete(run)
        return run

    def step_capture_spec(self, run: ProcedureRun, base: CaptureSpec) -> CaptureSpec:
        """Build the capture spec for the current step from the user's base spec."""
        step, rep = procedures.current(run)
        if step is None or step.kind != "capture":
            raise StateError("current step is not a capture step")
        d = procedures.get(run.procedure_id)
        sensors = {s.id: s for s in self.case().sensors}

        def kind_ok(ch: ChannelConfig, want: str) -> bool:
            k = sensors[ch.sensor_id].kind if ch.sensor_id in sensors else None
            if want == "vibration":
                return k in VIBRATION_KINDS
            if want == "acoustic":
                return k is None or k in ACOUSTIC_KINDS
            return True

        want = d.required_sensors[0] if d.required_sensors else "any"
        chans = []
        for ch in base.channels:
            pl = ch.placement
            if step.position_id and kind_ok(ch, want):
                pl = pl.model_copy(update={"position_id": step.position_id})
            if step.mounting is not None and kind_ok(ch, "vibration"):
                pl = pl.model_copy(update={"mounting": step.mounting})
            chans.append(ch.model_copy(update={"placement": pl}))
        state = dict(base.context.equipment_state)
        state.update(step.equipment_state)
        iv = procedures.latest_intervention(run) if any(
            s.kind == "intervention" for s in d.steps[: run.step_index]) else None
        ctx = base.context.model_copy(update={"condition_label": step.condition_label, "equipment_state": state, "intervention": iv,
                                              "procedure_run_id": run.id, "procedure_step": step.id,
                                              "procedure_revision": d.revision, "repeat_index": rep})
        return CaptureSpec(channels=chans, duration_s=step.duration_s or base.duration_s, context=ctx, backend=base.backend,
                           device=base.device, samplerate=step.sample_rate_hz or base.samplerate, exclusive=base.exclusive,
                           stimulus=step.stimulus, output_device=base.output_device)

    def _gate_stats(self, manifest: CaptureManifest, block: int = 1 << 20) -> tuple[bool, np.ndarray]:
        """(any |x| >= 0.999, per-channel std) computed in bounded blocks."""
        store = self._s()
        n, nch = manifest.frames, len(manifest.channels)
        clipped, s1, s2 = False, np.zeros(nch), np.zeros(nch)
        for a in range(0, n, block):
            d = store.load_capture_data(manifest, a, min(n, a + block)).astype(np.float64)
            clipped = clipped or bool(np.any(np.abs(d) >= 0.999))
            s1 += d.sum(axis=0)
            s2 += (d * d).sum(axis=0)
        mean = s1 / max(n, 1)
        return clipped, np.sqrt(np.maximum(s2 / max(n, 1) - mean * mean, 0.0))

    def evaluate_gates(self, run: ProcedureRun, manifest: CaptureManifest) -> list[str]:
        """Return failed gate messages (empty = accepted)."""
        step, _ = procedures.current(run)
        failed = []
        stats = None
        for g in step.gates:
            if g in ("no_clipping", "signal_present") and stats is None:
                stats = self._gate_stats(manifest)
            if g == "no_clipping" and stats[0]:
                failed.append("clipping: reduce the interface gain and repeat")
            elif g == "signal_present" and np.all(stats[1] < 1e-7):
                failed.append("no signal: check that the input is connected and not muted")
            elif g == "comparable_to_first":
                firsts = [c for k, v in run.captures.items() if not k.endswith("__rejected") for c in v]
                if firsts:
                    ref = self.capture(firsts[0])
                    for ch in manifest.channels:
                        iss = [i for i in comparability.check(ref, manifest, ch.label) if i.effect == "invalidates"]
                        if iss:
                            failed.append(f"not comparable with the first capture ({ch.label}): {iss[0].message}")
                            break
            elif g == "sync_shared_clock" and len(manifest.channels) < 2:
                failed.append("needs at least two channels from one device")
        if manifest.status != "complete":
            failed.append("capture ended early")
        return failed

    def record_step_capture(self, run_id: str, manifest: CaptureManifest) -> tuple[ProcedureRun, list[str]]:
        run = self.run(run_id)
        if self.settings.get("auto_analyze", True):
            self.analyze(manifest.id)
        failed = self.evaluate_gates(run, manifest)
        run = procedures.record_capture(run, manifest.id, accepted=not failed)
        self._save_run(run)
        self._s().audit("procedure.capture", run.id, f"{manifest.id} {'accepted' if not failed else 'rejected: ' + '; '.join(failed)}")
        if run.state == "completed":
            run = self._procedure_complete(run)
        return run, failed

    def run_step_capture(self, run_id: str, base: CaptureSpec) -> tuple[ProcedureRun, CaptureManifest | None, list[str]]:
        """Blocking helper (CLI/tests): capture the current step and record it."""
        run = self.run(run_id)
        spec = self.step_capture_spec(run, base)
        if spec.stimulus is not None and self.output.state.value != "armed":
            raise StateError("this step plays a test signal: arm the output first", code="SC_OUTPUT_NOT_ARMED")
        m = self.capture_blocking(spec)
        if m is None:
            return run, None, ["cancelled"]
        run, failed = self.record_step_capture(run_id, m)
        return run, m, failed

    def _procedure_complete(self, run: ProcedureRun) -> ProcedureRun:
        d = procedures.get(run.procedure_id)
        caps = {k: v for k, v in run.captures.items() if not k.endswith("__rejected")}
        labels = []
        allc = [c for v in caps.values() for c in v]
        if allc:
            labels = [ch.label for ch in self.capture(allc[0]).channels]
        outcome = []
        try:
            if d.analysis == "state_comparison":
                a = caps.get("on_1", []) + caps.get("on_2", [])
                b = caps.get("off", [])
                t = run.params.get("target", "")
                for lab in labels:
                    c = self.compare(a, b, lab, label_a=f"{t} on", label_b=f"{t} off", kind="state", run_id=run.id)
                    outcome.append(f"{lab}: {c.overall_delta_db:+.1f} dB (+/-{c.overall_uncertainty_db:.1f})"
                                   + ("" if c.comparable else " NOT COMPARABLE"))
                    if caps.get("on_1") and caps.get("on_2"):
                        self.compare(caps["on_1"], caps["on_2"], lab, label_a=f"{t} on (start)", label_b=f"{t} on (end)",
                                     kind="generic", run_id=run.id)
            elif d.analysis == "intervention":
                for lab in labels:
                    c = self.compare(caps.get("before", []), caps.get("after", []), lab, label_a=procedures.fill(d.steps[0].condition_label, run.params),
                                     label_b=procedures.fill(d.steps[-1].condition_label, run.params), kind="intervention", run_id=run.id)
                    outcome.append(f"{lab}: {c.overall_delta_db:+.1f} dB (+/-{c.overall_uncertainty_db:.1f}, "
                                   f"{'significant' if c.overall_significant else 'not significant'})")
            else:
                outcome.append(f"{len(allc)} captures recorded")
        except Exception as exc:  # noqa: BLE001 - keep the run completed; report analysis failure
            outcome.append(f"analysis failed: {exc}")
        run = procedures.complete_with_outcome(run, "; ".join(outcome))
        self._save_run(run)
        return run

    # ---------------- reports & archives ----------------
    def build_report(self, redact: tuple[str, ...] = ()):
        st = self._s()
        caps = []
        for m in st.list("capture"):
            a = st.latest_analysis(m.id)
            caps.append((m, a, st.load_arrays(a) if a else {}))
        n = len(st.list("report")) + 1
        inp = ReportInputs(case=st.case, captures=caps, comparisons=st.list("comparison"), diagnosis=self.latest_diagnosis(),
                           calibrations=st.list("calibration"), runs=st.list("procedure_run"), annotations=st.list("annotation"),
                           qualification={m.device.name: ("SIMULATED" if m.source == "simulated" else self.qualification.status(m.device.name))
                                          for m, _, _ in caps},
                           report_version=n, redact=tuple(redact), clock_mappings=st.list("clock_mapping"))
        return build_report(inp), caps

    def export_report(self, fmt: str, out_path: Path | None = None, redact: tuple[str, ...] = ()) -> Path:
        if fmt not in ("html", "pdf", "json", "csv"):
            raise ValidationError("format must be html, pdf, json or csv")
        (doc, figs), caps = self.build_report(redact)
        if fmt == "html":
            data = render.render_html(doc, figs)
        elif fmt == "pdf":
            data = render.render_pdf(doc, figs)
        elif fmt == "json":
            data = render.render_json(doc)
        else:
            extra = {}
            for m, a, arr in caps[:20]:
                if not a:
                    continue
                for ch in a.channels:
                    f, p = arr.get(f"f_{ch.channel}"), arr.get(f"psd_{ch.channel}")
                    if f is not None and p is not None:
                        extra[f"psd_{m.id}_{ch.label}"] = (["freq_hz", f"psd_{ch.unit}^2/Hz"], [[f"{x:.4f}", f"{y:.6e}"] for x, y in zip(f, p)])
            data = render.render_csv_zip(doc, extra)
        st = self._s()
        st.put("report", doc)
        ext = {"csv": "csv.zip"}.get(fmt, fmt)
        internal = st.path / "reports" / f"{doc.id}.{ext}"
        internal.write_bytes(data)
        if out_path:
            out_path = Path(out_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
        st.audit("report.export", doc.id, f"{fmt} v{doc.report_version} redact={','.join(redact)}")
        return out_path or internal

    def export_archive(self, out_path: Path, include_derived: bool = True) -> Path:
        export_case(self._s(), Path(out_path), include_derived)
        return Path(out_path)

    def import_archive(self, path: Path) -> str:
        return import_case(Path(path), self.workspace)

    def verify_case(self) -> list[str]:
        return self._s().verify()

    # ---------------- stimulus ----------------
    def arm_output(self, device: int | None = None, *, backend: str | None = None, level_limit_dbfs: float = -20.0,
                   max_duration_s: float = 30.0, samplerate: float = 48000.0, active_input_device: int | None = None,
                   allow_same_device: bool = False, confirmed: bool = False) -> None:
        be = self.backend(backend or self.settings.get("backend", "portaudio"))
        if self.output.backend is not be:
            self.output.stop()
            self.output = OutputController(be)
        dev = device if device is not None else (0 if be is self.sim else self.settings.get("output_device"))
        if dev is None:
            raise ValidationError("no output device selected", code="SC_NO_DEVICE")
        self.output.arm(dev, samplerate, level_limit_dbfs=level_limit_dbfs, max_duration_s=max_duration_s,
                        active_input_device=active_input_device, allow_same_device=allow_same_device, confirmed=confirmed)

    def audition(self, cid: str, channel_label: str, start_s: float = 0.0, seconds: float = 10.0) -> None:
        m = self.capture(cid)
        col = [c.label for c in m.channels].index(channel_label)
        x = self.capture_data(cid, start_s, start_s + seconds)[:, col]
        self.output.audition(x, m.sample_rate_hz)

    # ---------------- qualification ----------------
    def selftest(self) -> list[dict]:
        return selftest()

    def run_loopback(self, backend: str, out_device: int, in_device: int, samplerate: float = 48000.0) -> dict:
        be = self.backend(backend)
        res = loopback_test(be, out_device, in_device, samplerate)
        name = next((d.name for d in be.list_devices() if d.index == in_device), str(in_device))
        return self.qualification.add(name, backend, res, simulated=(backend == "simulated"))

    def environment(self) -> dict:
        import numpy
        import scipy

        try:
            import sounddevice as sd

            pa = sd.get_portaudio_version()[1]
        except Exception as exc:  # noqa: BLE001
            pa = f"unavailable ({exc})"
        return {"sonicclue": __version__, "build": BUILD_ID, "python": platform.python_version(), "os": platform.platform(),
                "numpy": numpy.__version__, "scipy": scipy.__version__, "portaudio": pa, "workspace": str(self.workspace.root)}

    def shutdown(self) -> None:
        try:
            self.output.stop()
        finally:
            self.jobs.shutdown(wait=True)
            self.close_case()

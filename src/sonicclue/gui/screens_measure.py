"""Screens 5, 6, 9: live measurement workspace, spectral & waveform analysis, before/after comparison."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from ..app.service import CaptureSpec
from ..domain import units
from ..domain.model import CaptureContext, StimulusRecord
from .common import (
    BAD,
    OK,
    PLOT_COLORS,
    WARN,
    GuiContext,
    LevelMeter,
    button,
    combo,
    confirm,
    error_box,
    fill_table,
    h1,
    log_plot,
    muted,
    row,
    table,
)


class LiveScreen(QWidget):
    title = "Live measurement"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        self.handle = None
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Live measurement"))
        self.cfg_lbl = muted("")
        lay.addWidget(self.cfg_lbl)
        top = QGroupBox("Condition being recorded")
        f = QFormLayout(top)
        self.label = QLineEdit()
        self.label.setPlaceholderText("e.g. baseline, fan off, after isolation pads")
        self.eq = QTableWidget(0, 2)
        self.eq.setHorizontalHeaderLabels(["Equipment", "State"])
        self.eq.horizontalHeader().setStretchLastSection(True)
        self.eq.setMaximumHeight(130)
        self.dur = QDoubleSpinBox()
        self.dur.setRange(1, 4 * 3600)
        self.dur.setValue(15)
        self.dur.setSuffix(" s")
        f.addRow("Condition label", self.label)
        f.addRow("Equipment states", self.eq)
        f.addRow("Duration", self.dur)
        lay.addWidget(top)
        self.start_b = button("Start recording", self.start, "primary", "Space")
        self.stop_b = button("Stop and keep", self.stop)
        self.cancel_b = button("Cancel and discard", self.cancel, "danger")
        self.elapsed = QLabel("idle")
        lay.addLayout(row(self.start_b, self.stop_b, self.cancel_b, self.elapsed, None))
        self.meters_box = QVBoxLayout()
        lay.addLayout(self.meters_box)
        self.meters: list[LevelMeter] = []
        self.plot = log_plot("Live spectrum (last second)", "dBFS")
        self.plot.setYRange(-140, 0)
        self.curves = []
        lay.addWidget(self.plot, 2)
        out = QGroupBox("Test signal (output)")
        of = QFormLayout(out)
        self.st_kind = combo([(k, k) for k in ("sine", "sweep", "pink", "white", "band_noise", "impulse")])
        self.st_freq = QDoubleSpinBox()
        self.st_freq.setRange(10, 20000)
        self.st_freq.setValue(1000)
        self.st_level = QDoubleSpinBox()
        self.st_level.setRange(-90, -6)
        self.st_level.setValue(-30)
        self.st_dur = QDoubleSpinBox()
        self.st_dur.setRange(0.5, 120)
        self.st_dur.setValue(5)
        self.out_dev = QComboBox()
        self.out_state = QLabel("DISARMED")
        of.addRow(muted("Test signals never start by themselves. Arm the output (with confirmation), then play. Esc stops at once."))
        of.addRow("Output device", self.out_dev)
        of.addRow("Signal", row(self.st_kind, QLabel("freq"), self.st_freq, QLabel("peak dBFS"), self.st_level, QLabel("s"), self.st_dur))
        of.addRow(row(button("Arm output...", self.arm), button("Play", self.play), button("STOP", self.stop_out, "danger"), self.out_state, None))
        lay.addWidget(out)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        ctx.caseChanged.connect(self.load)
        self.load()
        self._buttons()

    def load(self):
        spec = self.ctx.base_spec
        self.cfg_lbl.setText(f"Input: {spec.backend} device {spec.device}, {spec.samplerate:g} Hz, channels: "
                             + ", ".join(f"{c.label} (#{c.index}, sensor {c.sensor_id or '-'}, AGC {c.agc})" for c in spec.channels)
                             + ("  |  SIMULATED input" if spec.backend == "simulated" else "") + "  - change on the Devices screen.")
        self.eq.setRowCount(0)
        if self.ctx.app.store:
            for e in self.ctx.app.case().equipment:
                r = self.eq.rowCount()
                self.eq.insertRow(r)
                it = QTableWidgetItem(e.name)
                it.setData(Qt.UserRole, e.id)
                self.eq.setItem(r, 0, it)
                self.eq.setCellWidget(r, 1, combo([("on", "on"), ("off", "off"), ("not recorded", "")],
                                                  spec.context.equipment_state.get(e.id, "on")))
        for m in self.meters:
            m.setParent(None)
        self.meters = []
        for c in spec.channels:
            m = LevelMeter(c.label)
            self.meters_box.addWidget(m)
            self.meters.append(m)
        self.out_dev.clear()
        try:
            for d in self.ctx.app.devices(spec.backend):
                if d.max_output_channels > 0:
                    self.out_dev.addItem(f"[{d.index}] {d.name}", d.index)
        except Exception:  # noqa: BLE001
            self.out_dev.addItem("(no output devices)", None)

    def showEvent(self, e):  # noqa: N802 - Qt naming
        self.load()
        super().showEvent(e)

    def _buttons(self):
        running = self.handle is not None and self.handle.state.value in ("running", "stopping")
        self.start_b.setEnabled(not running)
        self.stop_b.setEnabled(running)
        self.cancel_b.setEnabled(running)

    def start(self):
        if not self.ctx.require_case(self):
            return
        spec = self.ctx.base_spec
        state = {}
        for r in range(self.eq.rowCount()):
            v = self.eq.cellWidget(r, 1).currentData()
            if v:
                state[self.eq.item(r, 0).data(Qt.UserRole)] = v
        ctx = CaptureContext(condition_label=self.label.text().strip(), equipment_state=state)
        run_spec = CaptureSpec(channels=spec.channels, duration_s=self.dur.value(), context=ctx, backend=spec.backend,
                               device=spec.device, samplerate=spec.samplerate, exclusive=spec.exclusive)
        try:
            self.handle = self.ctx.app.start_capture(run_spec)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot start recording", getattr(exc, "message", None) or str(exc))
            return
        self.curves = []
        self.plot.clear()
        self.plot.addLegend(offset=(10, 10))
        for i, c in enumerate(spec.channels):
            self.curves.append(self.plot.plot(pen=pg.mkPen(PLOT_COLORS[i % len(PLOT_COLORS)], width=1), name=c.label))
        self.timer.start()
        self._buttons()
        self.ctx.status.emit("recording ...")

    def tick(self):
        h = self.handle
        if h is None:
            self.timer.stop()
            return
        snap = h.session.snapshot()
        self.elapsed.setText(f"{snap.seconds:.1f} / {self.dur.value():.0f} s   dropouts {snap.gaps}")
        for m, pk, cl in zip(self.meters, snap.peak_dbfs, snap.clipped):
            m.set(pk, cl)
        x = snap.recent
        if len(x) >= 1024:
            n = 1 << int(np.log2(len(x)))
            seg = x[-n:]
            w = np.hanning(n)[:, None]
            spec = np.abs(np.fft.rfft(seg * w, axis=0)) ** 2 / (np.sum(w**2))
            f = np.fft.rfftfreq(n, 1 / self.ctx.base_spec.samplerate)
            db = 10 * np.log10(np.maximum(spec * 2 / n, 1e-20))
            for i, c in enumerate(self.curves):
                c.setData(f[1:], db[1:, i])
        if snap.state.value not in ("running", "stopping"):
            self.timer.stop()
            self.finish()

    def finish(self):
        h = self.handle

        def job(cancel):
            m = h.finalize(timeout=30)
            if m is not None and self.ctx.app.settings.get("auto_analyze", True):
                self.ctx.app.analyze(m.id, cancel=cancel)
            return m

        def done(m):
            self.handle = None
            self._buttons()
            if m is None:
                self.ctx.status.emit("recording discarded")
                return
            flags = ", ".join(q.code.value for q in m.quality if q.severity.value != "info")
            self.ctx.status.emit(f"saved {m.id} ({m.duration_s:.1f} s){' - ' + flags if flags else ''}")
            self.ctx.dataChanged.emit()

        self.ctx.run(job, done, on_error=lambda e: (setattr(self, "handle", None), self._buttons(),
                                                    error_box(self, "Recording failed", getattr(e, "message", str(e)))),
                     label="Saving recording")

    def stop(self):
        if self.handle:
            self.handle.stop()

    def cancel(self):
        if self.handle and confirm(self, "Discard recording", "Stop and discard this recording?"):
            self.handle.cancel()

    def arm(self):
        dev = self.out_dev.currentData()
        if dev is None:
            error_box(self, "No output", "No output device available.")
            return
        lim = self.st_level.value()
        if not confirm(self, "Arm test signal", f"Turn the amplifier/monitor volume DOWN before playing.\n\nArm output device {dev} with "
                                                f"a limit of {lim:.0f} dBFS peak for at most {self.st_dur.value():.0f} s? "
                                                "Arming expires after 30 s."):
            return
        spec = self.ctx.base_spec
        try:
            self.ctx.app.arm_output(dev, backend=spec.backend, level_limit_dbfs=lim, max_duration_s=self.st_dur.value(),
                                    samplerate=spec.samplerate, active_input_device=spec.device,
                                    allow_same_device=spec.backend == "simulated" or confirm(
                                        self, "Same device", "Output and input are on the same interface. Is acoustic feedback impossible "
                                                             "(headphones, or a loopback cable)?") if dev == spec.device else False,
                                    confirmed=True)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot arm output", getattr(exc, "message", None) or str(exc))
            return
        self.out_state.setText("ARMED")
        self.out_state.setStyleSheet(f"color:{WARN}; font-weight:600;")
        QTimer.singleShot(500, self._poll_out)

    def play(self):
        p = {"freq": self.st_freq.value(), "f0": 20.0, "f1": 20000.0}
        try:
            self.ctx.app.output.play(StimulusRecord(kind=self.st_kind.currentData(), level_dbfs=self.st_level.value(), params=p),
                                     self.st_dur.value())
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot play", getattr(exc, "message", None) or str(exc))
            return
        self.out_state.setText("PLAYING")
        self.out_state.setStyleSheet(f"color:{BAD}; font-weight:600;")
        QTimer.singleShot(300, self._poll_out)

    def stop_out(self):
        self.ctx.app.output.stop()
        self._poll_out()

    def _poll_out(self):
        st = self.ctx.app.output.state.value
        self.out_state.setText(st.upper())
        self.out_state.setStyleSheet(f"color:{ {'disarmed': OK, 'armed': WARN, 'playing': BAD}[st] }; font-weight:600;")
        if st != "disarmed":
            QTimer.singleShot(300, self._poll_out)


class AnalysisScreen(QWidget):
    title = "Analysis"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        self.cur = None
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Spectral and waveform analysis"))
        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        self.caps = QListWidget()
        self.caps.setAccessibleName("captures")
        self.caps.currentRowChanged.connect(self.select)
        lv.addWidget(QLabel("Captures"))
        lv.addWidget(self.caps)
        self.res = QDoubleSpinBox()
        self.res.setRange(0.05, 100)
        self.res.setValue(ctx.app.analysis_config().resolution_hz)
        self.win = combo([(w, w) for w in ("hann", "hamming", "blackmanharris", "flattop", "boxcar")], ctx.app.analysis_config().window)
        self.expert_box = QGroupBox("Analysis settings")
        ef = QFormLayout(self.expert_box)
        ef.addRow("Resolution (Hz)", self.res)
        ef.addRow("Window", self.win)
        lv.addWidget(self.expert_box)
        lv.addLayout(row(button("Re-analyse", self.reanalyse), button("Listen...", self.listen)))
        lv.addWidget(button("Import audio file...", self.import_file, tip="WAV/FLAC/AIFF; the original file is preserved byte-for-byte"))
        sp.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(140)
        rv.addWidget(self.summary)
        self.tabs = QTabWidget()
        self.psd = log_plot("Power spectral density", "dB re ref^2/Hz")
        self.tabs.addTab(self.psd, "Spectrum")
        self.wave = pg.PlotWidget(title="Waveform (min/max envelope)")
        self.wave.showGrid(x=True, y=True, alpha=0.25)
        self.wave.setLabel("bottom", "Time", units="s")
        self.tabs.addTab(self.wave, "Waveform")
        specw = QWidget()
        svl = QVBoxLayout(specw)
        self.spec_ch = QComboBox()
        self.spec_ch.currentIndexChanged.connect(self.draw_spectrogram)
        svl.addLayout(row(QLabel("Channel"), self.spec_ch, None))
        self.specplot = pg.PlotWidget(title="Spectrogram (dB)")
        self.specimg = pg.ImageItem()
        self.specplot.addItem(self.specimg)
        self.specplot.setLabel("bottom", "Time", units="s")
        self.specplot.setLabel("left", "Frequency", units="Hz")
        svl.addWidget(self.specplot)
        self.tabs.addTab(specw, "Spectrogram")
        self.coh = log_plot("Coherence between channels", "gamma^2")
        self.coh.setLogMode(x=True, y=False)
        self.coh.setYRange(0, 1.05)
        self.tabs.addTab(self.coh, "Coherence")
        self.env = pg.PlotWidget(title="Envelope (modulation) spectrum")
        self.env.setLabel("bottom", "Modulation frequency", units="Hz")
        self.tabs.addTab(self.env, "Envelope")
        self.peaks = table(["Channel", "Frequency Hz", "Level", "Prominence dB", "Q", "In cal. band"], stretch=None)
        self.tabs.addTab(self.peaks, "Tones (table)")
        self.bands = table(["Channel", "Band centre Hz", "Level", "Valid"])
        self.tabs.addTab(self.bands, "Bands (table)")
        self.flags = table(["Scope", "Code", "Severity", "Message"], stretch=3)
        self.tabs.addTab(self.flags, "Quality flags")
        rv.addWidget(self.tabs, 1)
        sp.addWidget(right)
        sp.setSizes([280, 900])
        lay.addWidget(sp)
        for s in (ctx.caseChanged, ctx.dataChanged):
            s.connect(self.refresh)
        ctx.modeChanged.connect(self.apply_mode)
        self.apply_mode()
        self.refresh()

    def apply_mode(self, *_):
        ex = self.ctx.expert
        self.expert_box.setVisible(ex)
        for i in (3, 4, 6):
            self.tabs.setTabVisible(i, ex)

    def refresh(self):
        self.caps.blockSignals(True)
        self.caps.clear()
        self._ids = []
        if self.ctx.app.store:
            for m in self.ctx.app.captures():
                it = QListWidgetItem(f"{m.created_utc:%m-%d %H:%M}  {m.context.condition_label or m.id}"
                                     + ("  [SIM]" if m.source == "simulated" else "") + ("  [partial]" if m.status != "complete" else ""))
                it.setToolTip(m.id)
                self.caps.addItem(it)
                self._ids.append(m.id)
        self.caps.blockSignals(False)
        if self._ids:
            self.caps.setCurrentRow(len(self._ids) - 1)
        else:
            self.summary.setPlainText("No captures yet. Record one on the Live screen or run a guided test.")
            for w in (self.psd, self.wave, self.coh, self.env):
                w.clear()

    def select(self, i):
        if i < 0 or i >= len(getattr(self, "_ids", [])):
            return
        cid = self._ids[i]
        self.summary.setPlainText("loading ...")
        self.ctx.run(lambda c: self._load(cid), self.show, label="Loading analysis")

    def _load(self, cid):
        app = self.ctx.app
        a = app.analysis(cid, ensure=True)
        return app.capture(cid), a, app.arrays(a)

    def reanalyse(self):
        if not self.cur:
            return
        cid = self.cur[0].id
        cfg = self.ctx.app.analysis_config().model_copy(update={"resolution_hz": self.res.value(), "window": self.win.currentData()})
        self.ctx.run(lambda c: (self.ctx.app.analyze(cid, cfg, cancel=c), self._load(cid))[1], self.show, label="Analysing")

    def show(self, data):
        self.cur = data
        m, a, arr = data
        lines = [f"{m.context.condition_label or m.id}: {m.duration_s:.1f} s at {m.sample_rate_hz:g} Hz, {m.device.name} "
                 f"({'SIMULATED' if m.source == 'simulated' else m.source}), capability tier {a.tier}"]
        for ch in a.channels:
            tones = ", ".join(f"{p.freq_hz:.1f} Hz" for p in ch.peaks[:5])
            if self.ctx.expert:
                lines.append(f"  {ch.label}: {ch.levels.level_db:.1f} {ch.levels.level_ref}, crest "
                             f"{ch.levels.crest_db.value if ch.levels.crest_db.value is not None else float('nan'):.1f} dB, floor "
                             f"{ch.noise_floor_db:.1f} dB/bin, {ch.n_averages} avg, df {ch.resolution_hz:.2f} Hz, ENBW {ch.enbw_hz:.2f} Hz, "
                             f"events {ch.transients.event_count}")
            else:
                desc = f"tones at {tones}" if tones else "no distinct tones"
                lines.append(f"  {ch.label}: level {ch.levels.level_db:.0f} {ch.levels.level_ref}; {desc}"
                             + (f"; {ch.transients.event_count} short impulsive events (possible rattle)" if ch.transients.event_count >= 3 else "")
                             + ("" if ch.calibrated else " (relative level, not calibrated)"))
        for cr in a.cross:
            if cr.coherent_peaks:
                lines.append(f"  channels {cr.ch_a}/{cr.ch_b} share components at {', '.join(f'{p.freq_hz:.0f}' for p in cr.coherent_peaks[:5])} Hz"
                             " (related signals - not proof of a path)")
        self.summary.setPlainText("\n".join(lines))
        # spectrum
        self.psd.clear()
        self.psd.addLegend(offset=(10, 10))
        for i, ch in enumerate(a.channels):
            f, p = arr.get(f"f_{ch.channel}"), arr.get(f"psd_{ch.channel}")
            if f is None:
                continue
            ref2 = units.DB_REFERENCE[ch.quantity] ** 2
            db = 10 * np.log10(np.maximum(p[1:], 1e-30) / ref2)
            col = PLOT_COLORS[i % len(PLOT_COLORS)]
            self.psd.plot(f[1:], db, pen=pg.mkPen(col, width=1), name=f"{ch.label} ({ch.levels.level_ref})")
            if ch.peaks:
                pf = np.array([pk.freq_hz for pk in ch.peaks])
                py = np.interp(pf, f[1:], db)
                self.psd.plot(pf, py, pen=None, symbol="t", symbolBrush=col, symbolSize=8)
        # waveform
        self.wave.clear()
        for i, ch in enumerate(a.channels):
            w = arr.get(f"wave_{ch.channel}")
            if w is None:
                continue
            t = np.linspace(0, m.duration_s, w.shape[1])
            col = PLOT_COLORS[i % len(PLOT_COLORS)]
            self.wave.plot(t, w[1], pen=pg.mkPen(col))
            self.wave.plot(t, w[0], pen=pg.mkPen(col))
        # spectrogram channel list
        self.spec_ch.blockSignals(True)
        self.spec_ch.clear()
        for ch in a.channels:
            self.spec_ch.addItem(ch.label, ch.channel)
        self.spec_ch.blockSignals(False)
        self.draw_spectrogram()
        # coherence
        self.coh.clear()
        self.coh.addLegend(offset=(10, 10))
        for i, cr in enumerate(a.cross):
            c, f = arr.get(f"coh_{cr.ch_a}_{cr.ch_b}"), arr.get(f"cohf_{cr.ch_a}_{cr.ch_b}")
            if c is None:
                continue
            ok = c >= 0
            self.coh.plot(f[ok][1:], c[ok][1:], pen=pg.mkPen(PLOT_COLORS[i % 6]), name=f"{cr.ch_a}-{cr.ch_b}"
                          + ("" if cr.eligible else " (NOT eligible)"))
            self.coh.addItem(pg.InfiniteLine(pos=cr.coherence_threshold, angle=0, pen=pg.mkPen(WARN, style=Qt.DashLine)))
        # envelope
        self.env.clear()
        for i, ch in enumerate(a.channels):
            f, p = arr.get(f"env_f_{ch.channel}"), arr.get(f"env_{ch.channel}")
            if f is not None and len(f) > 1:
                self.env.plot(f[1:], 10 * np.log10(np.maximum(p[1:], 1e-30)), pen=pg.mkPen(PLOT_COLORS[i % 6]))
        fill_table(self.peaks, [[ch.label, f"{p.freq_hz:.2f}", f"{p.level_db:.1f} {ch.levels.level_ref}", f"{p.prominence_db:.1f}",
                                 f"{p.q.value:.1f}" if p.q.status == "valid" else "resolution-limited", "yes" if p.cal_in_band else "no"]
                                for ch in a.channels for p in ch.peaks])
        fill_table(self.bands, [[ch.label, f"{b.center_hz:.1f}", f"{b.level_db:.1f}", "yes" if b.valid else "no"]
                                for ch in a.channels for b in ch.bands])
        fl = [["capture", q.code.value, q.severity.value, q.message] for q in a.quality] + \
             [[ch.label, q.code.value, q.severity.value, q.message] for ch in a.channels for q in ch.quality]
        fill_table(self.flags, fl, [BAD if r[2] == "invalid" else (WARN if r[2] == "warning" else None) for r in fl])

    def draw_spectrogram(self):
        if not self.cur:
            return
        _, a, arr = self.cur
        chn = self.spec_ch.currentData()
        s, f, t = arr.get(f"spec_{chn}"), arr.get(f"spec_f_{chn}"), arr.get(f"spec_t_{chn}")
        if s is None or s.size == 0:
            self.specimg.clear()
            return
        img = s.T
        lo, hi = np.percentile(img, 5), np.percentile(img, 99.5)
        self.specimg.setImage(img, levels=(lo, hi))
        self.specimg.setColorMap(pg.colormap.get("inferno"))
        from PySide6.QtCore import QRectF

        self.specimg.setRect(QRectF(0, 0, float(t[-1]) if len(t) else 1.0, float(f[-1]) if len(f) else 1.0))

    def import_file(self):
        if not self.ctx.require_case(self):
            return
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        path, _ = QFileDialog.getOpenFileName(self, "Import audio file", "", "Audio (*.wav *.flac *.aif *.aiff *.w64 *.rf64 *.caf *.ogg)")
        if not path:
            return
        label, ok = QInputDialog.getText(self, "Condition", "Condition label for this recording (e.g. 'baseline', 'fan off'):")
        if not ok:
            return
        from pathlib import Path as _P

        from ..domain.model import CaptureContext as _Ctx

        self.ctx.run(lambda c: self.ctx.app.import_audio(_P(path), context=_Ctx(condition_label=label.strip())),
                     lambda m: (self.ctx.status.emit(f"imported {m.id} ({m.duration_s:.1f} s, {len(m.channels)} ch)"),
                                self.ctx.dataChanged.emit()), label="Importing audio")

    def listen(self):
        if not self.cur:
            return
        m, a, _ = self.cur
        lab = a.channels[0].label
        dev = self.ctx.app.settings.get("output_device")
        spec = self.ctx.base_spec
        if not confirm(self, "Listen", f"Play up to 10 s of '{lab}' (normalised to -20 dBFS peak) on the output device? "
                                       "Turn the volume down first. Esc stops."):
            return
        try:
            self.ctx.app.arm_output(dev if dev is not None else (0 if spec.backend == "simulated" else None), backend=spec.backend,
                                    level_limit_dbfs=-20, max_duration_s=10, samplerate=m.sample_rate_hz, confirmed=True,
                                    allow_same_device=True)
            self.ctx.app.audition(m.id, lab, 0.0, 10.0)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot play", getattr(exc, "message", None) or str(exc))


class CompareScreen(QWidget):
    title = "Before / after"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Before / after comparison"))
        lay.addWidget(muted("Select the 'before' captures (A) and the 'after' captures (B). Two or more captures per side give measured "
                            "repeatability. SonicClue checks that the sensor, position, mounting, gain and AGC were the same."))
        sp = QSplitter(Qt.Horizontal)
        self.a, self.b = QListWidget(), QListWidget()
        for lst, name in ((self.a, "A (before)"), (self.b, "B (after)")):
            lst.setSelectionMode(QAbstractItemView.MultiSelection)
            w = QWidget()
            v = QVBoxLayout(w)
            v.addWidget(QLabel(name))
            v.addWidget(lst)
            sp.addWidget(w)
        lay.addWidget(sp, 1)
        self.chn = QComboBox()
        self.la, self.lb = QLineEdit("before"), QLineEdit("after")
        self.band_on = QCheckBox("Limit to band")
        self.lo, self.hi = QDoubleSpinBox(), QDoubleSpinBox()
        for s, v in ((self.lo, 20), (self.hi, 500)):
            s.setRange(1, 96000)
            s.setValue(v)
        lay.addLayout(row(QLabel("Channel"), self.chn, QLabel("Label A"), self.la, QLabel("Label B"), self.lb, self.band_on, self.lo,
                          QLabel("-"), self.hi, button("Compare", self.compare, "primary"), None))
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMaximumHeight(170)
        lay.addWidget(self.result)
        tabs = QTabWidget()
        self.chart = pg.PlotWidget(title="Band level change (B - A)")
        self.chart.setLogMode(x=True, y=False)
        self.chart.setLabel("bottom", "Band centre (Hz)")
        self.chart.getAxis("bottom").enableAutoSIPrefix(False)
        self.chart.setLabel("left", "dB")
        self.chart.showGrid(x=True, y=True, alpha=0.25)
        tabs.addTab(self.chart, "Bands")
        self.tones = table(["Tone Hz", "A dB", "B dB", "Change dB", "Status"])
        tabs.addTab(self.tones, "Tones")
        self.prev = table(["Created", "Conditions", "Channel", "Delta dB", "+/-", "Significant", "Comparable"], stretch=1)
        tabs.addTab(self.prev, "Previous comparisons")
        aw = QWidget()
        av = QVBoxLayout(aw)
        av.addWidget(muted("Two recordings made at the same time on different devices have independent clocks. Select the reference "
                           "capture in list A and the other in list B (one each), then estimate their clock mapping. Synchronized "
                           "analysis (coherence) is only allowed below the frequency the timing accuracy supports."))
        self.al_ref_ch, self.al_oth_ch = QComboBox(), QComboBox()
        av.addLayout(row(QLabel("Reference channel"), self.al_ref_ch, QLabel("Other channel"), self.al_oth_ch,
                         button("Estimate clock mapping", self.align), None))
        self.al_out = QPlainTextEdit()
        self.al_out.setReadOnly(True)
        av.addWidget(self.al_out)
        tabs.addTab(aw, "Align (multi-device)")
        lay.addWidget(tabs, 2)
        for s in (ctx.caseChanged, ctx.dataChanged):
            s.connect(self.refresh)
        self.refresh()

    def refresh(self):
        for lst in (self.a, self.b):
            lst.clear()
        self.chn.clear()
        if not self.ctx.app.store:
            return
        labels = []
        for m in self.ctx.app.captures():
            for lst in (self.a, self.b):
                it = QListWidgetItem(f"{m.context.condition_label or '-'}  {m.created_utc:%m-%d %H:%M}  {m.id}")
                it.setData(Qt.UserRole, m.id)
                lst.addItem(it)
            for c in m.channels:
                if c.label not in labels:
                    labels.append(c.label)
        for lab in labels:
            self.chn.addItem(lab, lab)
        for cb in (self.al_ref_ch, self.al_oth_ch):
            cb.clear()
            for lab in labels:
                cb.addItem(lab, lab)
        fill_table(self.prev, [[c.created_utc.strftime("%m-%d %H:%M"), f"{c.label_a} -> {c.label_b}", c.channel_label,
                                f"{c.overall_delta_db:+.1f}", f"{c.overall_uncertainty_db:.1f}", "yes" if c.overall_significant else "no",
                                "yes" if c.comparable else "NO"] for c in reversed(self.ctx.app.comparisons())])

    def compare(self):
        a = [i.data(Qt.UserRole) for i in self.a.selectedItems()]
        b = [i.data(Qt.UserRole) for i in self.b.selectedItems()]
        if not a or not b:
            error_box(self, "Select captures", "Select at least one capture on each side.")
            return
        if set(a) & set(b):
            error_box(self, "Overlap", "A capture cannot be on both sides.")
            return
        band = (self.lo.value(), self.hi.value()) if self.band_on.isChecked() else None
        lab = self.chn.currentData()
        la, lb = self.la.text() or "A", self.lb.text() or "B"
        self.ctx.run(lambda c: self.ctx.app.compare(a, b, lab, label_a=la, label_b=lb, band=band), self.show, label="Comparing")

    def align(self):
        a = [i.data(Qt.UserRole) for i in self.a.selectedItems()]
        b = [i.data(Qt.UserRole) for i in self.b.selectedItems()]
        if len(a) != 1 or len(b) != 1 or a == b:
            error_box(self, "Select captures", "Select exactly one reference capture (A) and one other capture (B).")
            return
        rc, oc = self.al_ref_ch.currentData(), self.al_oth_ch.currentData()

        def done(r):
            m = r["mapping"]
            lines = [f"offset {m.offset_s * 1000:.3f} ms, drift {m.drift_ppm:+.2f} ppm, timing uncertainty {m.residual_s * 1e6:.1f} us",
                     f"Synchronized analysis allowed below {m.eligible_max_freq_hz:.0f} Hz" if m.eligible_max_freq_hz > 0 else
                     "Synchronized analysis NOT allowed - only independent spectral comparison is valid."]
            lines += [f"[{f.severity.value}] {f.message}" for f in r["flags"]]
            if r["coherent"]:
                lines.append("Coherent components: " + ", ".join(f"{fq:.1f} Hz ({c:.2f})" for fq, c in r["coherent"])
                             + " - related signals, not proof of a path")
            self.al_out.setPlainText("\n".join(lines))

        self.ctx.run(lambda c: self.ctx.app.align_captures(a[0], b[0], rc, oc), done, label="Estimating clock mapping")

    def show(self, c):
        lines = [f"{c.label_a} -> {c.label_b} on '{c.channel_label}': {c.overall_delta_db:+.2f} dB +/- {c.overall_uncertainty_db:.2f} dB (95%), "
                 f"{'SIGNIFICANT' if c.overall_significant else 'not significant'} ({c.repeatability} repeatability)",
                 "Comparable: " + ("yes" if c.comparable else "NO - this result cannot be used as evidence")]
        if c.changed_equipment:
            lines.append("Equipment changed: " + ", ".join(f"{k}: {v[0]} -> {v[1]}" for k, v in c.changed_equipment.items()))
        lines += [f"  [{i.effect}] {i.message}" for i in c.issues]
        self.result.setPlainText("\n".join(lines))
        self.chart.clear()
        if c.band_deltas:
            x = np.array([b.center_hz for b in c.band_deltas])
            y = np.array([b.delta_db for b in c.band_deltas])
            brushes = [pg.mkBrush(OK if (b.significant and b.delta_db < 0) else (BAD if b.significant else "#555")) for b in c.band_deltas]
            self.chart.addItem(pg.BarGraphItem(x=np.log10(x), height=y, width=0.08, brushes=brushes))
        fill_table(self.tones, [[f"{t.freq_hz:.1f}", t.level_a_db, t.level_b_db, t.delta_db, t.status] for t in c.tone_deltas])
        self.ctx.dataChanged.emit()



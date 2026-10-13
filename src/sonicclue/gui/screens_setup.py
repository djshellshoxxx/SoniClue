"""Screens 3, 4, 12: device & sensor configuration, calibration manager, settings & hardware qualification."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QTabWidget,
)

from .. import BUILD_ID, __version__
from ..app.service import CaptureSpec
from ..domain.model import (
    DEFAULT_QUANTITY,
    RELATIVE_ONLY_KINDS,
    AnalysisConfig,
    ChannelConfig,
    Mounting,
    Placement,
    SensorDescriptor,
    SensorKind,
)
from ..sensors import calibration as cal
from ..sensors.capabilities import capabilities
from .common import GuiContext, button, combo, confirm, error_box, fill_table, h1, muted, row, table

RATES = [44100, 48000, 88200, 96000, 192000]


class DevicesScreen(QWidget):
    title = "Devices & sensors"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Devices and sensors"))
        lay.addWidget(muted("Choose the audio interface and describe every input channel: which sensor, where it is, how it is "
                            "mounted, the interface gain and whether automatic gain control (AGC) is off. Comparisons are only "
                            "trusted when these stay the same."))
        top = QGroupBox("Audio interface")
        f = QFormLayout(top)
        self.backend = combo([("PortAudio (WASAPI / MME / ALSA ...)", "portaudio"), ("Built-in simulator (SIMULATED data)", "simulated")])
        self.backend.currentIndexChanged.connect(self.refresh_devices)
        self.device = QComboBox()
        self.device.setAccessibleName("input device")
        self.rate = combo([(f"{r} Hz", float(r)) for r in RATES], 48000.0)
        self.exclusive = QCheckBox("WASAPI exclusive mode (bypasses Windows mixer and enhancements)")
        self.dev_msg = muted("")
        f.addRow("Backend", self.backend)
        f.addRow("Input device", row(self.device, button("Refresh", self.refresh_devices)))
        f.addRow("Sample rate", self.rate)
        f.addRow("", self.exclusive)
        f.addRow("", self.dev_msg)
        lay.addWidget(top)
        chb = QGroupBox("Input channels")
        cv = QVBoxLayout(chb)
        self.ch = QTableWidget(0, 9)
        self.ch.setHorizontalHeaderLabels(["Input #", "Label", "Sensor", "Position id", "Location", "Mounting", "Gain dB", "AGC", "Calibration"])
        self.ch.horizontalHeader().setStretchLastSection(True)
        cv.addWidget(self.ch)
        self.tier = muted("")
        cv.addLayout(row(button("Add channel", self.add_channel), button("Remove channel", lambda: self.ch.removeRow(self.ch.currentRow())),
                         None, button("Apply configuration", self.apply, "primary")))
        cv.addWidget(self.tier)
        lay.addWidget(chb, 2)
        sb = QGroupBox("Sensors in this investigation")
        sv = QVBoxLayout(sb)
        self.sensors = table(["Id", "Kind", "Model", "Serial", "Quantity", "Notes"], stretch=5)
        sv.addWidget(self.sensors)
        self.s_id, self.s_model, self.s_serial = QLineEdit(), QLineEdit(), QLineEdit()
        self.s_kind = combo([(k.value.replace("_", " "), k) for k in SensorKind])
        sv.addLayout(row(QLabel("Id"), self.s_id, QLabel("Kind"), self.s_kind, QLabel("Model"), self.s_model, QLabel("Serial"),
                         self.s_serial, button("Add / update sensor", self.add_sensor)))
        lay.addWidget(sb, 1)
        ctx.caseChanged.connect(self.load)
        ctx.dataChanged.connect(self.refresh_cal_options)
        self.load()

    # ---------------- devices ----------------
    def refresh_devices(self):
        self.device.clear()
        be = self.backend.currentData()
        try:
            devs = [d for d in self.ctx.app.devices(be) if d.max_input_channels > 0]
            for d in devs:
                self.device.addItem(f"[{d.index}] {d.name} ({d.host_api}, {d.max_input_channels} in)", d.index)
            self.dev_msg.setText("" if devs else "No input devices found. Connect an interface, or use the simulator.")
            if be == "simulated":
                self.dev_msg.setText("Simulator: all recordings will be marked SIMULATED and are not physical measurements.")
            st = self.ctx.app.qualification
            if devs and be == "portaudio":
                self.dev_msg.setText("Qualification: " + "; ".join(f"{d.name}: {st.status(d.name)}" for d in devs[:4]))
        except Exception as exc:  # noqa: BLE001
            self.dev_msg.setText(f"Audio backend unavailable: {getattr(exc, 'message', exc)}. Use the simulator or install drivers.")
        spec = self.ctx.base_spec
        if spec.device is not None:
            i = self.device.findData(spec.device)
            if i >= 0:
                self.device.setCurrentIndex(i)

    # ---------------- channels ----------------
    def _sensor_combo(self, current):
        items = [("(none)", None)]
        if self.ctx.app.store:
            items += [(f"{s.id} ({s.kind.value})", s.id) for s in self.ctx.app.case().sensors]
        return combo(items, current)

    def _cal_combo(self, current):
        items = [("(none: relative dBFS)", None)]
        if self.ctx.app.store:
            items += [(f"{c.id} [{c.sensor_id}]", c.id) for c in self.ctx.app.calibrations()]
        return combo(items, current)

    def add_channel(self, ch: ChannelConfig | None = None):
        r = self.ch.rowCount()
        ch = ch or ChannelConfig(index=r, label=f"ch{r + 1}", agc="unknown")
        self.ch.insertRow(r)
        sp = QSpinBox()
        sp.setRange(0, 63)
        sp.setValue(ch.index)
        self.ch.setCellWidget(r, 0, sp)
        self.ch.setItem(r, 1, QTableWidgetItem(ch.label))
        self.ch.setCellWidget(r, 2, self._sensor_combo(ch.sensor_id))
        self.ch.setItem(r, 3, QTableWidgetItem(ch.placement.position_id))
        self.ch.setItem(r, 4, QTableWidgetItem(ch.placement.location))
        self.ch.setCellWidget(r, 5, combo([(m.value, m) for m in Mounting], ch.placement.mounting))
        g = QDoubleSpinBox()
        g.setRange(-61, 90)
        g.setSpecialValueText("unknown")
        g.setValue(ch.input_gain_db if ch.input_gain_db is not None else -61)
        self.ch.setCellWidget(r, 6, g)
        self.ch.setCellWidget(r, 7, combo([("off", "off"), ("on", "on"), ("unknown", "unknown")], ch.agc))
        self.ch.setCellWidget(r, 8, self._cal_combo(ch.calibration_id))

    def refresh_cal_options(self):
        for r in range(self.ch.rowCount()):
            cur = self.ch.cellWidget(r, 8).currentData()
            self.ch.setCellWidget(r, 8, self._cal_combo(cur))

    def read_channels(self) -> list[ChannelConfig]:
        out = []
        for r in range(self.ch.rowCount()):
            g = self.ch.cellWidget(r, 6).value()
            out.append(ChannelConfig(index=self.ch.cellWidget(r, 0).value(), label=(self.ch.item(r, 1).text() or f"ch{r + 1}").strip(),
                                     sensor_id=self.ch.cellWidget(r, 2).currentData(), calibration_id=self.ch.cellWidget(r, 8).currentData(),
                                     input_gain_db=None if g <= -61 else g, agc=self.ch.cellWidget(r, 7).currentData(),
                                     placement=Placement(position_id=(self.ch.item(r, 3).text() if self.ch.item(r, 3) else "").strip(),
                                                         location=(self.ch.item(r, 4).text() if self.ch.item(r, 4) else "").strip(),
                                                         mounting=self.ch.cellWidget(r, 5).currentData())))
        return out

    def apply(self):
        try:
            chans = self.read_channels()
            if not chans:
                raise ValueError("add at least one channel")
            if self.ctx.app.store:
                self.ctx.app._validate_channels(chans)
            be = self.backend.currentData()
            dev = self.device.currentData()
            if dev is None:
                raise ValueError("select an input device")
            self.ctx.app.backend(be).check_input(dev, self.rate.currentData(), max(c.index for c in chans) + 1)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Configuration not valid", getattr(exc, "message", None) or str(exc).splitlines()[0])
            return
        old = self.ctx.base_spec
        self.ctx.base_spec = CaptureSpec(channels=chans, duration_s=old.duration_s, backend=be, device=dev,
                                         samplerate=self.rate.currentData(), exclusive=self.exclusive.isChecked(), context=old.context)
        if be == "portaudio":
            self.ctx.app.save_settings(backend=be, device=dev, samplerate=self.rate.currentData())
        warn = [c.label for c in chans if c.agc != "off"]
        self.update_tier(chans)
        self.ctx.status.emit("capture configuration applied" + (f"; AGC not confirmed off on {', '.join(warn)}" if warn else ""))
        if warn:
            QMessageBox.warning(self, "AGC not confirmed off",
                                "Level comparisons are invalid while automatic gain control is on or unknown (channels: "
                                + ", ".join(warn) + "). Set AGC to 'off' once you have disabled it in the interface/driver.")

    def update_tier(self, chans):
        if not self.ctx.app.store:
            return
        sensors = {s.id: s for s in self.ctx.app.case().sensors}
        cals = {c.id: c for c in self.ctx.app.calibrations()}
        calibrated = {c.index for c in chans if c.calibration_id in cals and
                      cal.evaluate(cals[c.calibration_id], c, sensors.get(c.sensor_id)).usable}
        caps = capabilities(chans, sensors, calibrated)
        self.tier.setText(f"Capability tier {caps.tier}: " + ("absolute levels; " if caps.absolute_levels else "relative levels (dBFS); ")
                          + ("synchronized cross-channel analysis; " if caps.synchronized_cross_channel else "")
                          + ("vibration (relative); " if caps.vibration_relative and not caps.vibration_physical else "")
                          + " ".join(caps.notes))

    # ---------------- sensors ----------------
    def add_sensor(self):
        if not self.ctx.require_case(self):
            return
        try:
            k = self.s_kind.currentData()
            s = SensorDescriptor(id=self.s_id.text().strip(), kind=k, quantity=DEFAULT_QUANTITY[k], model=self.s_model.text().strip(),
                                 serial=self.s_serial.text().strip())
            self.ctx.app.add_sensor(s)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Invalid sensor", str(exc).splitlines()[0])
            return
        self.load_sensors()
        for r in range(self.ch.rowCount()):
            cur = self.ch.cellWidget(r, 2).currentData()
            self.ch.setCellWidget(r, 2, self._sensor_combo(cur))

    def load_sensors(self):
        rows = []
        if self.ctx.app.store:
            for s in self.ctx.app.case().sensors:
                note = "relative only (cannot be calibrated)" if s.kind in RELATIVE_ONLY_KINDS else s.notes
                rows.append([s.id, s.kind.value, s.model, s.serial, s.quantity.value, note])
        fill_table(self.sensors, rows)

    def load(self):
        spec = self.ctx.base_spec
        i = self.backend.findData(spec.backend)
        self.backend.blockSignals(True)
        self.backend.setCurrentIndex(max(0, i))
        self.backend.blockSignals(False)
        self.refresh_devices()
        self.ch.setRowCount(0)
        chans = spec.channels
        if self.ctx.app.store:
            sids = {s.id for s in self.ctx.app.case().sensors}
            first = next(iter(sorted(sids)), None)
            chans = [c.model_copy(update={"sensor_id": c.sensor_id if c.sensor_id in sids else (first if c.index == 0 else None),
                                          "calibration_id": None}) for c in chans]
        for c in chans:
            self.add_channel(c)
        self.load_sensors()
        self.update_tier(chans)


class CalibrationScreen(QWidget):
    title = "Calibration"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Calibration manager"))
        lay.addWidget(muted("Without calibration SonicClue reports relative levels (dBFS), which is enough for most comparisons. "
                            "Calibration converts to pascals or m/s^2 and is only valid for the sensor, interface and gain it was "
                            "made with. Contact pickups cannot be calibrated."))
        self.tbl = table(["Id", "Sensor", "Quantity", "Sensitivity (FS/unit)", "Ref gain dB", "Valid band Hz", "+/- dB (k=2)", "Method",
                          "Created", "Expires"], stretch=0)
        lay.addWidget(self.tbl, 1)
        tabs = QTabWidget()
        # calibrator
        w1 = QWidget()
        f1 = QFormLayout(w1)
        self.cap = QComboBox()
        self.cap.currentIndexChanged.connect(self._cap_changed)
        self.chn = QComboBox()
        self.ref_level = QDoubleSpinBox()
        self.ref_level.setRange(0.001, 200)
        self.ref_level.setValue(94.0)
        self.ref_level.setDecimals(3)
        self.ref_freq = QDoubleSpinBox()
        self.ref_freq.setRange(10, 20000)
        self.ref_freq.setValue(1000.0)
        self.unc = QDoubleSpinBox()
        self.unc.setRange(0, 5)
        self.unc.setValue(0.4)
        f1.addRow(muted("Record 5-10 s of the calibrator mounted on the sensor (Live screen, condition 'calibration'), then select it here."))
        f1.addRow("Calibrator recording", self.cap)
        f1.addRow("Channel", self.chn)
        f1.addRow("Reference level (dB SPL, or m/s^2 RMS)", self.ref_level)
        f1.addRow("Reference frequency (Hz)", self.ref_freq)
        f1.addRow("Calibrator uncertainty (dB)", self.unc)
        f1.addRow(button("Calibrate", self.calibrate, "primary"))
        tabs.addTab(w1, "From calibrator recording")
        # file
        w2 = QWidget()
        f2 = QFormLayout(w2)
        self.f_sensor = QComboBox()
        self.f_path = QLineEdit()
        self.f_kind = combo([("sensor response (deviation from flat; will be negated)", "response"), ("correction (dB to add)", "correction")])
        self.f_sens = QDoubleSpinBox()
        self.f_sens.setDecimals(6)
        self.f_sens.setRange(1e-6, 1e6)
        self.f_sens.setValue(0.01)
        self.f_gain = QDoubleSpinBox()
        self.f_gain.setRange(-61, 90)
        self.f_gain.setSpecialValueText("unknown")
        self.f_gain.setValue(-61)
        f2.addRow("Sensor", self.f_sensor)
        f2.addRow("Response file", row(self.f_path, button("Browse...", self._browse)))
        f2.addRow("File contains", self.f_kind)
        f2.addRow("Sensitivity (FS per unit)", self.f_sens)
        f2.addRow("Interface gain (dB)", self.f_gain)
        f2.addRow(button("Import", self.import_file, "primary"))
        tabs.addTab(w2, "From response file")
        # library
        w3 = QWidget()
        v3 = QVBoxLayout(w3)
        self.lib = table(["Id", "Sensor", "Method", "Created"], stretch=0)
        v3.addWidget(muted("Profiles you created in other investigations. Copying one keeps its provenance."))
        v3.addWidget(self.lib)
        v3.addLayout(row(button("Copy selected into this investigation", self.copy_lib), None))
        tabs.addTab(w3, "Library")
        lay.addWidget(tabs, 1)
        self.status_lbl = muted("")
        lay.addWidget(self.status_lbl)
        ctx.caseChanged.connect(self.refresh)
        ctx.dataChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        app = self.ctx.app
        self.cap.clear()
        self.f_sensor.clear()
        rows = []
        if app.store:
            for c in app.calibrations():
                rows.append([c.id, c.sensor_id, c.quantity.value, f"{c.sensitivity_fs_per_unit:.5g}",
                             "-" if c.reference_gain_db is None else c.reference_gain_db, f"{c.valid_band_hz[0]:g}-{c.valid_band_hz[1]:g}",
                             f"{c.uncertainty_db:.2f}", c.method, c.created_utc.strftime("%Y-%m-%d"),
                             c.expires_utc.strftime("%Y-%m-%d") if c.expires_utc else "-"])
            for m in app.captures():
                self.cap.addItem(f"{m.id}  {m.context.condition_label or ''}  ({m.duration_s:.0f} s)", m.id)
            for s in app.case().sensors:
                if s.kind not in RELATIVE_ONLY_KINDS:
                    self.f_sensor.addItem(f"{s.id} ({s.kind.value})", s.id)
            spec = self.ctx.base_spec
            sensors = {s.id: s for s in app.case().sensors}
            cals = {c.id: c for c in app.calibrations()}
            msgs = []
            for ch in spec.channels:
                st = cal.evaluate(cals.get(ch.calibration_id), ch, sensors.get(ch.sensor_id))
                msgs.append(f"{ch.label}: {'calibrated' if st.usable else 'relative'}" + (f" ({st.flags[0].message})" if st.flags else ""))
            self.status_lbl.setText("Current channels - " + "; ".join(msgs))
        fill_table(self.tbl, rows)
        fill_table(self.lib, [[c.id, c.sensor_id, c.method, c.created_utc.strftime("%Y-%m-%d")] for c in app.library_calibrations()])

    def _cap_changed(self):
        self.chn.clear()
        cid = self.cap.currentData()
        if cid and self.ctx.app.store:
            for ch in self.ctx.app.capture(cid).channels:
                self.chn.addItem(f"{ch.label} (sensor {ch.sensor_id or '-'})", ch.label)

    def calibrate(self):
        if not self.ctx.require_case(self) or not self.cap.currentData():
            return
        cid, lab = self.cap.currentData(), self.chn.currentData()
        lvl, fq, unc = self.ref_level.value(), self.ref_freq.value(), self.unc.value()
        self.ctx.run(lambda c: self.ctx.app.calibrate_from_capture(cid, lab, lvl, fq, calibrator_uncertainty_db=unc),
                     lambda p: (self.ctx.dataChanged.emit(), QMessageBox.information(self, "Calibration created",
                                f"{p.id}: {p.sensitivity_fs_per_unit:.5g} FS per unit, +/-{p.uncertainty_db:.2f} dB.\nAssign it to the channel "
                                "on the Devices screen.")), label="Calibrating")

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Frequency response file", "", "Text (*.txt *.frd *.cal *.csv);;All (*)")
        if p:
            self.f_path.setText(p)

    def import_file(self):
        if not self.ctx.require_case(self) or not self.f_sensor.currentData():
            return
        try:
            g = self.f_gain.value()
            p = self.ctx.app.calibration_from_file(self.f_sensor.currentData(), Path(self.f_path.text()), self.f_kind.currentData(),
                                                   self.f_sens.value(), gain_db=None if g <= -61 else g)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Import failed", getattr(exc, "message", None) or str(exc))
            return
        self.ctx.dataChanged.emit()
        self.ctx.status.emit(f"calibration {p.id} imported")

    def copy_lib(self):
        r = self.lib.currentRow()
        if r < 0 or not self.ctx.require_case(self):
            return
        cid = self.lib.item(r, 0).text()
        prof = next(c for c in self.ctx.app.library_calibrations() if c.id == cid)
        if prof.sensor_id not in {s.id for s in self.ctx.app.case().sensors}:
            error_box(self, "Sensor missing", f"Add sensor '{prof.sensor_id}' to this investigation first.")
            return
        self.ctx.app.add_calibration(prof, to_library=False)
        self.ctx.dataChanged.emit()


class SettingsScreen(QWidget):
    title = "Settings & qualification"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Settings and hardware qualification"))
        g = QGroupBox("General")
        f = QFormLayout(g)
        self.mode = combo([("Guided (plain language)", "guided"), ("Expert (numerical detail)", "expert")], ctx.mode)
        self.mode.currentIndexChanged.connect(lambda: ctx.set_mode(self.mode.currentData()))
        self.auto = QCheckBox("Analyse captures automatically")
        self.auto.setChecked(bool(ctx.app.settings.get("auto_analyze", True)))
        self.auto.toggled.connect(lambda v: ctx.app.save_settings(auto_analyze=v))
        f.addRow("Mode", self.mode)
        f.addRow("Workspace", QLabel(str(ctx.app.workspace.root)))
        f.addRow("", self.auto)
        lay.addWidget(g)
        a = QGroupBox("Analysis defaults (expert)")
        fa = QFormLayout(a)
        cfg = ctx.app.analysis_config()
        self.res = QDoubleSpinBox()
        self.res.setRange(0.05, 100)
        self.res.setValue(cfg.resolution_hz)
        self.mina = QSpinBox()
        self.mina.setRange(1, 1000)
        self.mina.setValue(cfg.min_averages)
        self.win = combo([(w, w) for w in ("hann", "hamming", "blackmanharris", "flattop", "boxcar")], cfg.window)
        self.prom = QDoubleSpinBox()
        self.prom.setRange(3, 60)
        self.prom.setValue(cfg.tone_prominence_db)
        fa.addRow("Target resolution (Hz)", self.res)
        fa.addRow("Minimum independent averages", self.mina)
        fa.addRow("Window", self.win)
        fa.addRow("Tone prominence (dB)", self.prom)
        fa.addRow(button("Save analysis defaults", self.save_analysis))
        lay.addWidget(a)
        q = QGroupBox("Hardware qualification")
        qv = QVBoxLayout(q)
        qv.addWidget(muted("Self-test checks the numerical engine of this installation. Loopback qualification needs a cable from "
                           "an output to an input of the same interface. Turn monitors OFF first. Only a passed loopback on real "
                           "hardware marks a device QUALIFIED; every other device is UNQUALIFIED."))
        self.out_dev = QSpinBox()
        self.out_dev.setRange(0, 255)
        self.in_dev = QSpinBox()
        self.in_dev.setRange(0, 255)
        self.q_backend = combo([("PortAudio", "portaudio"), ("Simulator (records SIMULATED, never QUALIFIED)", "simulated")])
        qv.addLayout(row(button("Run self-test", self.selftest), None, QLabel("Backend"), self.q_backend, QLabel("Output #"), self.out_dev,
                         QLabel("Input #"), self.in_dev, button("Run loopback qualification", self.loopback)))
        self.qtbl = table(["Device", "Backend", "OS", "Build", "Date", "Status", "Results"], stretch=6)
        qv.addWidget(self.qtbl)
        lay.addWidget(q, 1)
        info = QPlainTextEdit()
        info.setReadOnly(True)
        info.setMaximumHeight(110)
        env = ctx.app.environment()
        info.setPlainText(f"SonicClue {__version__} (build {BUILD_ID}) by Circuit Drift Labs\n" +
                          "\n".join(f"{k}: {v}" for k, v in env.items()) + "\nThird-party licences: see THIRD_PARTY_NOTICES.md in the install folder.")
        lay.addWidget(info)
        self.refresh_q()

    def save_analysis(self):
        try:
            cur = dict(self.ctx.app.settings.get("analysis", {}))
            cur.update(resolution_hz=self.res.value(), min_averages=self.mina.value(), window=self.win.currentData(),
                       tone_prominence_db=self.prom.value())
            AnalysisConfig(**cur)
            self.ctx.app.save_settings(analysis=cur)
            self.ctx.status.emit("analysis defaults saved (applies to new analyses)")
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Invalid settings", str(exc).splitlines()[0])

    def selftest(self):
        self.ctx.run(lambda c: self.ctx.app.selftest(),
                     lambda res: QMessageBox.information(self, "Self-test", "\n".join(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}"
                                                                                       for r in res)), label="Self-test")

    def loopback(self):
        if not confirm(self, "Loopback qualification", "Connect a cable from the selected output to the selected input, and turn "
                                                       "monitors/headphones down. A -20 dBFS test tone will play for ~8 s. Continue?"):
            return
        be, o, i = self.q_backend.currentData(), self.out_dev.value(), self.in_dev.value()
        self.ctx.run(lambda c: self.ctx.app.run_loopback(be, o, i), lambda rec: (self.refresh_q(), QMessageBox.information(
            self, "Qualification", f"{rec['device']}: {rec['status']}")), label="Loopback qualification")

    def refresh_q(self):
        fill_table(self.qtbl, [[r["device"], r["backend"], r["os"], r["build"], r["date"][:16], r["status"],
                                ", ".join(f"{k}={v}" for k, v in r["results"].items())] for r in reversed(self.ctx.app.qualification.records)])



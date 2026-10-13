"""Screens 7, 8, 11: hypothesis & evidence panel, guided test workspace, report builder."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
)
from PySide6.QtGui import QColor

from .. import procedures
from ..domain.model import InterventionRecord
from .common import (
    BAD,
    CLASS_COLOR,
    LEVEL_COLOR,
    MUTED,
    OK,
    WARN,
    GuiContext,
    button,
    combo,
    confirm,
    error_box,
    h1,
    muted,
    row,
)

CONCLUSION_TEXT = {
    "leading_explanation": ("One explanation is supported by the evidence", OK),
    "multiple_explanations": ("Several explanations are supported - they may act together", WARN),
    "inconclusive": ("Inconclusive - SonicClue abstains until more evidence is collected", MUTED),
}


class HypothesesScreen(QWidget):
    title = "Hypotheses & evidence"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Hypotheses and evidence"))
        lay.addWidget(muted("Support levels are judgements from fixed, versioned rules: strongly supported > supported > undetermined > "
                            "weakened > contradicted. They are not probabilities. Correlation is never treated as proof of cause."))
        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("font-size:12pt; padding:8px;")
        lay.addLayout(row(button("Update diagnosis", self.run, "primary", "Re-evaluate all evidence"), button("Add note to selected...", self.note),
                          None))
        lay.addWidget(self.banner)
        sp = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Hypothesis / detail", "Support"])
        self.tree.setColumnWidth(0, 760)
        self.tree.setAccessibleName("hypotheses")
        sp.addWidget(self.tree)
        self.evidence = QTreeWidget()
        self.evidence.setHeaderLabels(["Evidence", "Class", "Usable"])
        self.evidence.setColumnWidth(0, 820)
        sp.addWidget(self.evidence)
        self.next = QListWidget()
        sp.addWidget(self.next)
        sp.setSizes([380, 260, 140])
        lay.addWidget(sp, 1)
        lay.addLayout(row(button("Start selected next test", self.start_next), None))
        for s in (ctx.caseChanged, ctx.diagnosisChanged):
            s.connect(self.refresh)
        self.refresh()

    def run(self):
        if not self.ctx.require_case(self):
            return
        self.ctx.run(lambda c: self.ctx.app.diagnose(), lambda s: self.ctx.diagnosisChanged.emit(), label="Diagnosing")

    def refresh(self):
        self.tree.clear()
        self.evidence.clear()
        self.next.clear()
        if not self.ctx.app.store:
            self.banner.setText("No investigation open.")
            return
        d = self.ctx.app.latest_diagnosis()
        if d is None:
            self.banner.setText("No diagnosis yet. Record a baseline, then press 'Update diagnosis'.")
            return
        txt, col = CONCLUSION_TEXT[d.conclusion]
        self.banner.setText(txt + ("\n" + "\n".join("- " + r for r in d.abstention_reasons) if d.abstention_reasons else ""))
        self.banner.setStyleSheet(f"font-size:12pt; padding:8px; border-left:4px solid {col}; background:#152033;")
        ev = {e.id: e for e in d.evidence}
        for h in d.hypotheses:
            it = QTreeWidgetItem([h.statement, h.level.value.replace("_", " ")])
            it.setForeground(1, QColor(LEVEL_COLOR[h.level.value]))
            it.setData(0, Qt.UserRole, h.id)
            for line in h.explanation:
                QTreeWidgetItem(it, ["why: " + line, ""])
            for eid in h.supporting:
                if eid in ev:
                    c = QTreeWidgetItem(it, ["+ " + ev[eid].summary, ev[eid].statement_class.value])
                    c.setForeground(0, QColor(OK))
            for eid in h.contradicting:
                if eid in ev:
                    c = QTreeWidgetItem(it, ["- " + ev[eid].summary, ev[eid].statement_class.value])
                    c.setForeground(0, QColor(BAD))
            for t in h.missing_tests:
                pid, _, prm = t.partition(":")
                try:
                    QTreeWidgetItem(it, ["missing test: " + procedures.get(pid).title + (f" ({prm})" if prm else ""), ""])
                except Exception:  # noqa: BLE001
                    pass
            if self.ctx.expert:
                QTreeWidgetItem(it, ["rules: " + ", ".join(h.rules), ""])
            self.tree.addTopLevelItem(it)
        for e in d.evidence:
            it = QTreeWidgetItem([e.summary, e.statement_class.value, "yes" if e.valid else "no"])
            it.setForeground(1, QColor(CLASS_COLOR[e.statement_class.value]))
            if not e.valid:
                it.setForeground(0, QColor(MUTED))
            self.evidence.addTopLevelItem(it)
        self._next = d.next_tests
        for t in d.next_tests:
            li = QListWidgetItem(f"{t.title} {t.params or ''} - {t.reason}" + ("" if t.available else f"  [unavailable: {t.unavailable_reason}]"))
            li.setToolTip(t.reason)
            self.next.addItem(li)

    def note(self):
        it = self.tree.currentItem()
        while it is not None and it.parent() is not None:
            it = it.parent()
        if it is None:
            return
        text, ok = QInputDialog.getMultiLineText(self, "Note", f"Note on: {it.text(0)}")
        if ok and text.strip():
            self.ctx.app.annotate(it.data(0, Qt.UserRole), text.strip())
            self.ctx.status.emit("note saved (user assertion)")

    def start_next(self):
        i = self.next.currentRow()
        if i < 0:
            return
        t = self._next[i]
        if not t.available:
            error_box(self, "Not available", t.unavailable_reason)
            return
        try:
            run = self.ctx.app.start_procedure(t.procedure_id, t.params)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot start", getattr(exc, "message", None) or str(exc))
            return
        self.ctx.runSelected.emit(run.id)
        self.ctx.navigate.emit("guided")


class GuidedScreen(QWidget):
    title = "Guided tests"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        self.run_id = None
        self.handle = None
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Guided tests"))
        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Procedures"))
        self.lib = QListWidget()
        self.lib.currentRowChanged.connect(self.describe)
        lv.addWidget(self.lib)
        self.param = QComboBox()
        self.param.setEditable(True)
        self.param_lbl = QLabel("Parameter")
        lv.addLayout(row(self.param_lbl, self.param))
        lv.addWidget(button("Start procedure", self.start, "primary"))
        self.desc = QTextBrowser()
        lv.addWidget(self.desc, 1)
        sp.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        self.run_title = h1("No active test")
        rv.addWidget(self.run_title)
        self.progress = QProgressBar()
        rv.addWidget(self.progress)
        self.steps = QListWidget()
        self.steps.setMaximumHeight(170)
        rv.addWidget(self.steps)
        self.instr = QPlainTextEdit()
        self.instr.setReadOnly(True)
        self.instr.setStyleSheet("font-size:12pt;")
        rv.addWidget(self.instr, 1)
        self.iv_box = QGroupBox("Describe the change you made")
        ivf = QFormLayout(self.iv_box)
        self.iv_desc = QLineEdit()
        self.iv_src = QCheckBox("changes the source itself (speed, power, operating state)")
        self.iv_path = QCheckBox("changes the transmission path (mounting, isolation, damping, distance)")
        self.iv_rcv = QCheckBox("changes the receiver (the affected object or position)")
        self.iv_setup = QCheckBox("changes the measurement setup (sensor, gain, position)")
        ivf.addRow("Description", self.iv_desc)
        for cb in (self.iv_src, self.iv_path, self.iv_rcv, self.iv_setup):
            ivf.addRow(cb)
        rv.addWidget(self.iv_box)
        self.cap_prog = QProgressBar()
        rv.addWidget(self.cap_prog)
        self.gate = QLabel("")
        self.gate.setWordWrap(True)
        rv.addWidget(self.gate)
        self.act = button("Continue", self.act_step, "primary")
        self.pause_b = button("Pause", self.pause)
        self.cancel_b = button("Cancel test", self.cancel, "danger")
        self.diag_b = button("Update diagnosis", self.diagnose)
        rv.addLayout(row(self.act, self.pause_b, self.cancel_b, None, self.diag_b))
        sp.addWidget(right)
        sp.setSizes([380, 820])
        lay.addWidget(sp)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)
        ctx.runSelected.connect(self.select_run)
        ctx.caseChanged.connect(self.reset)
        self._lib = list(procedures.library().values())
        for d in self._lib:
            self.lib.addItem(f"{d.title}  (tier {d.min_tier}+)")
        self.reset()

    def reset(self):
        self.run_id = None
        if self.ctx.app.store:
            act = [r for r in self.ctx.app.runs() if r.state in ("running", "paused")]
            if act:
                self.run_id = act[-1].id
        self.render()
        self.describe(self.lib.currentRow())

    def describe(self, i):
        if i < 0:
            return
        d = self._lib[i]
        self.param.clear()
        need = d.parameters[0] if d.parameters else None
        self.param_lbl.setText({"target": "Equipment", "object": "Object"}.get(need, "Parameter"))
        self.param.setEnabled(bool(need))
        if need == "target" and self.ctx.app.store:
            for e in self.ctx.app.case().equipment:
                self.param.addItem(e.name, e.id)
        html = (f"<h3>{d.title}</h3><p>{d.purpose}</p><p><b>Difficulty:</b> {d.difficulty}/3 &nbsp; <b>Sensors:</b> "
                f"{', '.join(d.required_sensors)} &nbsp; <b>Minimum tier:</b> {d.min_tier}</p>")
        for title, items in (("Before you start", d.preconditions), ("Safety", d.safety), ("What can mislead this test", d.confounds)):
            if items:
                html += f"<p><b>{title}</b></p><ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>"
        html += f"<p><b>Steps:</b> {len(d.steps)} - {d.success}</p>"
        self.desc.setHtml(html)

    def start(self):
        if not self.ctx.require_case(self):
            return
        i = self.lib.currentRow()
        if i < 0:
            return
        d = self._lib[i]
        params = {}
        if d.parameters:
            val = self.param.currentData() or self.param.currentText().strip()
            if not val:
                error_box(self, "Parameter needed", f"Choose the {d.parameters[0]} for this test.")
                return
            params[d.parameters[0]] = val
        if self.run_id and not confirm(self, "Test in progress", "Another test is active. Pause it and start this one?"):
            return
        if self.run_id:
            try:
                self.ctx.app.procedure_action(self.run_id, "pause")
            except Exception:  # noqa: BLE001
                pass
        try:
            run = self.ctx.app.start_procedure(d.id, params)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot start", getattr(exc, "message", None) or str(exc))
            return
        self.run_id = run.id
        self.render()

    def select_run(self, rid):
        self.run_id = rid
        self.render()

    def render(self):
        self.gate.setText("")
        self.iv_box.setVisible(False)
        self.cap_prog.setVisible(False)
        if not self.run_id or not self.ctx.app.store:
            self.run_title.setText("No active test")
            self.steps.clear()
            self.instr.setPlainText("Choose a procedure on the left, or start a recommended test from the Hypotheses screen.")
            for b in (self.act, self.pause_b, self.cancel_b):
                b.setEnabled(False)
            return
        run = self.ctx.app.run(self.run_id)
        d = procedures.get(run.procedure_id)
        self.run_title.setText(procedures.fill(d.title, run.params) + f"  [{run.state}]")
        p, n = procedures.progress(run)
        self.progress.setRange(0, n)
        self.progress.setValue(p)
        self.steps.clear()
        for i, s in enumerate(d.steps):
            mark = "done" if i < run.step_index else ("now" if i == run.step_index else "")
            it = QListWidgetItem(f"{i + 1}. {procedures.fill(s.title, run.params)}" + (f" x{s.repeats}" if s.repeats > 1 else "")
                                 + (f"  - {mark}" if mark else ""))
            if mark == "now":
                it.setForeground(QColor(WARN))
            elif mark == "done":
                it.setForeground(QColor(OK))
            self.steps.addItem(it)
        self.pause_b.setText("Resume" if run.state == "paused" else "Pause")
        self.pause_b.setEnabled(run.state in ("running", "paused"))
        self.cancel_b.setEnabled(run.state in ("running", "paused"))
        if run.state != "running":
            self.instr.setPlainText(f"Test {run.state}." + (f"\nOutcome: {run.outcome}" if run.outcome else "")
                                    + ("\n\nPress 'Update diagnosis' to include the results." if run.state == "completed" else ""))
            self.act.setEnabled(False)
            return
        step, rep = procedures.current(run)
        text = step.instruction
        if self.ctx.expert and step.expert_note:
            text += f"\n\n[expert] {step.expert_note}"
        if step.kind == "capture":
            text += f"\n\nRecording {step.duration_s:g} s" + (f" after {step.settle_s:g} s settling" if step.settle_s else "") + \
                    (f" - repeat {rep + 1} of {step.repeats}" if step.repeats > 1 else "")
            if step.equipment_state:
                text += "\nExpected state: " + ", ".join(f"{k} {v}" for k, v in step.equipment_state.items())
            if step.stimulus:
                text += f"\nA test signal ({step.stimulus.kind}, {step.stimulus.level_dbfs:g} dBFS peak) will play: you will be asked to arm the output."
            self.act.setText("Record")
        elif step.kind == "intervention":
            self.iv_box.setVisible(True)
            self.act.setText("Save change and continue")
        else:
            self.act.setText("Done - continue")
        self.instr.setPlainText(text)
        self.act.setEnabled(self.handle is None)

    def act_step(self):
        run = self.ctx.app.run(self.run_id)
        step, rep = procedures.current(run)
        try:
            if step.kind == "instruction":
                run = self.ctx.app.procedure_action(run.id, "ack")
            elif step.kind == "intervention":
                if not self.iv_desc.text().strip():
                    error_box(self, "Description needed", "Describe what you changed.")
                    return
                rec = InterventionRecord(description=self.iv_desc.text().strip(), target=run.params.get("target", run.params.get("object", "")),
                                         changes_source_output=self.iv_src.isChecked(), changes_transmission_path=self.iv_path.isChecked(),
                                         changes_receiver=self.iv_rcv.isChecked(), changes_measurement_setup=self.iv_setup.isChecked())
                run = self.ctx.app.procedure_action(run.id, "intervention", record=rec)
            else:
                self.record(run, step)
                return
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Step failed", getattr(exc, "message", None) or str(exc))
        self.ctx.dataChanged.emit()
        self.render()

    def record(self, run, step):
        spec = self.ctx.app.step_capture_spec(run, self.ctx.base_spec)
        if spec.stimulus is not None:
            spec_b = self.ctx.base_spec
            if not confirm(self, "Arm test signal", "This step plays a test signal through the output. Turn the volume DOWN, then confirm."):
                return
            try:
                dev = self.ctx.app.settings.get("output_device")
                self.ctx.app.arm_output(dev if dev is not None else (0 if spec_b.backend == "simulated" else None), backend=spec_b.backend,
                                        level_limit_dbfs=-12, max_duration_s=spec.duration_s + 2, samplerate=spec.samplerate,
                                        active_input_device=spec_b.device, allow_same_device=spec_b.backend == "simulated", confirmed=True)
            except Exception as exc:  # noqa: BLE001
                error_box(self, "Cannot arm output", getattr(exc, "message", None) or str(exc))
                return
        self.act.setEnabled(False)
        self.cap_prog.setVisible(True)
        self.cap_prog.setRange(0, int(step.settle_s + spec.duration_s) * 10 or 1)
        self._t0 = time.monotonic()
        self._settle = step.settle_s if spec.backend != "simulated" else min(step.settle_s, 0.5)
        self._spec = spec
        self.gate.setText(f"Settling {self._settle:g} s - keep still ..." if self._settle else "Recording ...")
        self.timer.start()

    def tick(self):
        el = time.monotonic() - self._t0
        self.cap_prog.setValue(int(el * 10))
        if self.handle is None:
            if el >= self._settle:
                try:
                    self.handle = self.ctx.app.start_capture(self._spec)
                    self.gate.setText("Recording ...")
                except Exception as exc:  # noqa: BLE001
                    self.timer.stop()
                    self.act.setEnabled(True)
                    error_box(self, "Cannot record", getattr(exc, "message", None) or str(exc))
            return
        if self.handle.state.value in ("running", "stopping"):
            return
        self.timer.stop()
        h, rid = self.handle, self.run_id

        def job(cancel):
            m = h.finalize(timeout=30)
            if m is None:
                return None, []
            run, failed = self.ctx.app.record_step_capture(rid, m)
            return m, failed

        def done(res):
            self.handle = None
            m, failed = res
            self.ctx.dataChanged.emit()
            self.render()
            if failed:
                self.gate.setText("Capture rejected: " + "; ".join(failed) + ". Fix the problem and record again.")
                self.gate.setStyleSheet(f"color:{BAD};")
            elif m is not None:
                self.gate.setText(f"Capture {m.id} accepted.")
                self.gate.setStyleSheet(f"color:{OK};")

        self.ctx.run(job, done, on_error=lambda e: (setattr(self, "handle", None), self.render(),
                                                    error_box(self, "Recording failed", getattr(e, "message", str(e)))),
                     label="Saving and checking capture")

    def pause(self):
        run = self.ctx.app.run(self.run_id)
        self.ctx.app.procedure_action(run.id, "resume" if run.state == "paused" else "pause")
        self.render()

    def cancel(self):
        if confirm(self, "Cancel test", "Cancel this test? Captures already recorded are kept."):
            if self.handle:
                self.handle.cancel()
            self.ctx.app.procedure_action(self.run_id, "cancel")
            self.render()

    def diagnose(self):
        if self.ctx.require_case(self):
            self.ctx.run(lambda c: self.ctx.app.diagnose(), lambda s: (self.ctx.diagnosisChanged.emit(), self.ctx.navigate.emit("hypotheses")),
                         label="Diagnosing")


class ReportScreen(QWidget):
    title = "Report builder"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Report builder"))
        lay.addWidget(muted("Reports label every statement: MEASURED, CALCULATED, INFERRED, USER (your input) or UNRESOLVED. Redaction removes "
                            "names, locations, serial numbers or notes from the exported file."))
        self.fmt = combo([("HTML", "html"), ("PDF", "pdf"), ("JSON (machine-readable)", "json"), ("CSV tables (zip)", "csv")])
        self.red = {k: QCheckBox(k) for k in ("names", "locations", "serials", "notes")}
        self.rediag = QCheckBox("Update diagnosis first")
        self.rediag.setChecked(True)
        lay.addLayout(row(QLabel("Format"), self.fmt, QLabel("Redact:"), *self.red.values(), self.rediag, None,
                          button("Preview", self.preview), button("Export...", self.export, "primary")))
        self.view = QTextBrowser()
        lay.addWidget(self.view, 1)
        self.last = muted("")
        lay.addWidget(self.last)

    def _redact(self):
        return tuple(k for k, cb in self.red.items() if cb.isChecked())

    def preview(self):
        if not self.ctx.require_case(self):
            return
        red, rd = self._redact(), self.rediag.isChecked()

        def job(c):
            from ..reporting.render import render_html

            if rd:
                self.ctx.app.diagnose()
            (doc, figs), _ = self.ctx.app.build_report(red)
            return render_html(doc, figs).decode()

        self.ctx.run(job, lambda html: (self.view.setHtml(html), self.ctx.diagnosisChanged.emit()), label="Building report preview")

    def export(self):
        if not self.ctx.require_case(self):
            return
        fmt = self.fmt.currentData()
        ext = {"csv": "csv.zip"}.get(fmt, fmt)
        path, _ = QFileDialog.getSaveFileName(self, "Export report", f"{self.ctx.app.case().id}-report.{ext}")
        if not path:
            return
        red, rd = self._redact(), self.rediag.isChecked()

        def job(c):
            if rd:
                self.ctx.app.diagnose()
            return self.ctx.app.export_report(fmt, Path(path), red)

        def done(p):
            self.last.setText(f"Written: {p}")
            self.ctx.diagnosisChanged.emit()
            if confirm(self, "Report exported", f"Report written to\n{p}\n\nOpen the folder?"):
                folder = str(Path(p).parent)
                if sys.platform.startswith("win"):
                    os.startfile(folder)  # noqa: S606 - user-requested
                else:
                    subprocess.Popen(["xdg-open", folder])  # noqa: S603,S607

        self.ctx.run(job, done, label="Exporting report")

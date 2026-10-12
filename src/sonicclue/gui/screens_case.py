"""Screens 1, 2, 10: case dashboard, new investigation wizard, diagnostic history."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
    QComboBox,
)

from ..domain.model import DEFAULT_QUANTITY, Equipment, ProblemDescription, SensorDescriptor, SensorKind
from .common import (
    GuiContext,
    button,
    confirm,
    error_box,
    fill_table,
    h1,
    muted,
    row,
    table,
)

CHARACTERS = ["hum", "buzz", "rattle", "whine", "rumble", "tonal", "broadband", "intermittent", "continuous", "felt_vibration"]
EQ_KINDS = ["fan", "computer", "hvac", "speaker", "amplifier", "machine", "appliance", "lighting", "power", "other"]


def slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:30] or "item"
    s, i = base, 2
    while s in taken:
        s = f"{base}_{i}"
        i += 1
    return s


class DashboardScreen(QWidget):
    title = "Case dashboard"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Investigations"))
        lay.addWidget(muted("Each investigation (case) keeps its measurements, analyses, tests, hypotheses and reports together. "
                            "Original recordings are never modified."))
        self.tbl = table(["Title", "Last change (UTC)", "Captures", "Status", "Id"], stretch=0)
        self.tbl.doubleClicked.connect(self.open_selected)
        self.tbl.setAccessibleName("investigation list")
        self.empty = muted("No investigations yet. Create one, or open the simulated demo to see a complete example.")
        lay.addLayout(row(button("New investigation...", self.new_case, "primary", "Ctrl+N"), button("Open", self.open_selected),
                          button("Open demo (simulated)", self.demo, tip="Runs a complete simulated investigation"),
                          button("Import archive...", self.import_archive), button("Export archive...", self.export_archive),
                          button("Verify integrity", self.verify), button("Delete...", self.delete, "danger"), None))
        lay.addWidget(self.empty)
        lay.addWidget(self.tbl, 2)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setAccessibleName("current investigation summary")
        box = QGroupBox("Current investigation")
        bl = QVBoxLayout(box)
        bl.addWidget(self.summary)
        lay.addWidget(box, 1)
        ctx.caseChanged.connect(self.refresh)
        ctx.dataChanged.connect(self.refresh_summary)
        ctx.diagnosisChanged.connect(self.refresh_summary)
        self.refresh()

    def refresh(self):
        cases = self.ctx.app.list_cases()
        cur = self.ctx.app.store.case.id if self.ctx.app.store else None
        rows, colors = [], []
        for c in cases:
            st = "OPEN" if c["id"] == cur else ("locked by another instance" if c["locked"] else "")
            if c["error"]:
                st = "DAMAGED: " + c["error"][:60]
            rows.append([c["title"], c["updated"][:19].replace("T", " "), c["captures"], st, c["id"]])
            colors.append("#f85149" if c["error"] else ("#3fa7ff" if c["id"] == cur else None))
        fill_table(self.tbl, rows, colors)
        self.empty.setVisible(not cases)
        self.refresh_summary()

    def refresh_summary(self):
        app = self.ctx.app
        if app.store is None:
            self.summary.setPlainText("No investigation open.")
            return
        c = app.case()
        caps = app.captures()
        dx = app.latest_diagnosis()
        lines = [f"{c.title}  [{c.id}]", "", f"Problem: {c.problem.summary or '-'}",
                 f"Character: {', '.join(c.problem.character) or '-'}    Receiver: {c.problem.receiver or '-'}",
                 f"Equipment: {', '.join(f'{e.name} ({e.id})' for e in c.equipment) or '- (add candidate equipment so tests can be suggested)'}",
                 f"Sensors: {', '.join(f'{s.id} [{s.kind.value}]' for s in c.sensors) or '-'}",
                 f"Captures: {len(caps)}" + (f" ({sum(m.source == 'simulated' for m in caps)} SIMULATED)" if any(m.source == 'simulated' for m in caps) else ""),
                 f"Procedure runs: {len(app.runs())}    Comparisons: {len(app.comparisons())}"]
        if dx:
            lines += ["", f"Latest diagnosis ({dx.created_utc:%Y-%m-%d %H:%M}): {dx.conclusion.replace('_', ' ')}"]
            lines += [f"  [{h.level.value}] {h.statement}" for h in dx.hypotheses[:4]]
            if dx.next_tests:
                lines.append(f"Suggested next: {dx.next_tests[0].title}")
        self.summary.setPlainText("\n".join(lines))

    def _selected_id(self):
        r = self.tbl.currentRow()
        return self.tbl.item(r, 4).text() if r >= 0 and self.tbl.item(r, 4) else None

    def open_selected(self):
        cid = self._selected_id()
        if not cid:
            return
        try:
            self.ctx.app.open_case(cid)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot open investigation", getattr(exc, "message", str(exc)))
            return
        rec = self.ctx.app.store.recovered
        if rec:
            QMessageBox.information(self, "Recovered captures", f"{len(rec)} interrupted capture(s) were recovered and marked as partial.")
        self.ctx.caseChanged.emit()
        self.ctx.status.emit(f"opened {cid}")

    def new_case(self):
        w = NewCaseWizard(self.ctx, self)
        if w.exec() == QWizard.Accepted and w.created:
            self.ctx.caseChanged.emit()
            self.ctx.navigate.emit("devices")

    def demo(self):
        if not confirm(self, "Simulated demo", "This creates a new investigation filled with SIMULATED measurements (about one minute). "
                                               "It demonstrates the workflow and is not a real measurement. Continue?"):
            return
        from ..app.demo import run_demo
        from ..app.service import SonicClueApp

        root = self.ctx.app.workspace.root

        def job(cancel):
            demo_app = SonicClueApp(root, sim_speed=40.0)
            try:
                cid = run_demo(demo_app, progress=lambda m: None, duration_scale=0.6)
            finally:
                demo_app.shutdown()
            return cid

        def done(cid):
            self.ctx.app.open_case(cid)
            self.ctx.caseChanged.emit()
            self.ctx.diagnosisChanged.emit()
            self.ctx.navigate.emit("hypotheses")

        self.ctx.app.close_case()
        self.ctx.caseChanged.emit()
        self.ctx.run(job, done, label="Running simulated demo")

    def import_archive(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import case archive", "", "SonicClue archive (*.scarchive *.zip)")
        if path:
            self.ctx.run(lambda c: self.ctx.app.import_archive(Path(path)), lambda cid: (self.refresh(), self.ctx.status.emit(f"imported {cid}")),
                         label="Importing archive")

    def export_archive(self):
        if not self.ctx.require_case(self):
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export case archive", f"{self.ctx.app.case().id}.scarchive", "SonicClue archive (*.scarchive)")
        if path:
            self.ctx.run(lambda c: self.ctx.app.export_archive(Path(path)), lambda p: self.ctx.status.emit(f"archive written: {p}"),
                         label="Exporting archive")

    def verify(self):
        if not self.ctx.require_case(self):
            return

        def done(probs):
            if probs:
                error_box(self, "Integrity problems found", f"{len(probs)} problem(s)", "\n".join(probs))
            else:
                QMessageBox.information(self, "Integrity", "Database, documents and all capture checksums verified.")

        self.ctx.run(lambda c: self.ctx.app.verify_case(), done, label="Verifying")

    def delete(self):
        cid = self._selected_id()
        if not cid or not confirm(self, "Delete investigation", f"Permanently delete {cid} and all its recordings? This cannot be undone."):
            return
        try:
            self.ctx.app.delete_case(cid)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot delete", getattr(exc, "message", str(exc)))
        self.ctx.caseChanged.emit()


class NewCaseWizard(QWizard):
    def __init__(self, ctx: GuiContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.created = None
        self.setWindowTitle("New investigation")
        self.setMinimumSize(720, 520)
        # page 1: problem
        p1 = QWizardPage()
        p1.setTitle("Describe the problem")
        p1.setSubTitle("What do you hear or feel, where, and when? This is recorded as your observation, not as a measurement.")
        f = QFormLayout(p1)
        self.title_ed = QLineEdit()
        self.title_ed.setPlaceholderText("e.g. Low hum on vocal recordings")
        p1.registerField("title*", self.title_ed)
        self.summary_ed = QPlainTextEdit()
        self.summary_ed.setMaximumHeight(90)
        self.receiver_ed = QLineEdit()
        self.receiver_ed.setPlaceholderText("e.g. vocal microphone at the desk")
        self.when_ed = QLineEdit()
        grid = QGridLayout()
        self.chars = {}
        for i, c in enumerate(CHARACTERS):
            cb = QCheckBox(c.replace("_", " "))
            self.chars[c] = cb
            grid.addWidget(cb, i // 5, i % 5)
        self.band_on = QCheckBox("I know roughly which frequencies")
        self.f_lo, self.f_hi = QDoubleSpinBox(), QDoubleSpinBox()
        for sp, v in ((self.f_lo, 20), (self.f_hi, 500)):
            sp.setRange(1, 24000)
            sp.setValue(v)
            sp.setSuffix(" Hz")
        f.addRow("Title *", self.title_ed)
        f.addRow("Description", self.summary_ed)
        f.addRow("Character", grid)
        f.addRow("Affected receiver", self.receiver_ed)
        f.addRow("When does it occur?", self.when_ed)
        f.addRow(self.band_on, row(self.f_lo, QLabel("to"), self.f_hi, None))
        self.addPage(p1)
        # page 2: equipment
        p2 = QWizardPage()
        p2.setTitle("Candidate equipment")
        p2.setSubTitle("List equipment that might be involved and that you can switch on and off safely. SonicClue only suggests "
                       "on/off tests for equipment listed here.")
        v = QVBoxLayout(p2)
        self.eq_tbl = QTableWidget(0, 2)
        self.eq_tbl.setHorizontalHeaderLabels(["Name", "Kind"])
        self.eq_tbl.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.eq_tbl)
        v.addLayout(row(button("Add equipment", self.add_eq), button("Remove selected", lambda: self.eq_tbl.removeRow(self.eq_tbl.currentRow())), None))
        self.addPage(p2)
        # page 3: sensors
        p3 = QWizardPage()
        p3.setTitle("Sensors")
        p3.setSubTitle("Which sensors will you use? A microphone alone is enough to start. Contact pickups add relative vibration "
                       "information; accelerometers can give physical units when calibrated.")
        v3 = QVBoxLayout(p3)
        self.s_tbl = QTableWidget(0, 3)
        self.s_tbl.setHorizontalHeaderLabels(["Id", "Kind", "Model"])
        self.s_tbl.horizontalHeader().setStretchLastSection(True)
        v3.addWidget(self.s_tbl)
        v3.addLayout(row(button("Add sensor", self.add_sensor), button("Remove selected", lambda: self.s_tbl.removeRow(self.s_tbl.currentRow())), None))
        self.add_sensor(SensorKind.STUDIO_MIC)
        self.addPage(p3)

    def add_eq(self):
        r = self.eq_tbl.rowCount()
        self.eq_tbl.insertRow(r)
        self.eq_tbl.setItem(r, 0, QTableWidgetItem("Computer"))
        cb = QComboBox()
        cb.addItems(EQ_KINDS)
        self.eq_tbl.setCellWidget(r, 1, cb)

    def add_sensor(self, kind=None):
        r = self.s_tbl.rowCount()
        self.s_tbl.insertRow(r)
        self.s_tbl.setItem(r, 0, QTableWidgetItem(f"sensor{r + 1}" if r else "mic1"))
        cb = QComboBox()
        for k in SensorKind:
            cb.addItem(k.value, k)
        if isinstance(kind, SensorKind):
            cb.setCurrentIndex(cb.findData(kind))
        self.s_tbl.setCellWidget(r, 1, cb)
        self.s_tbl.setItem(r, 2, QTableWidgetItem(""))

    def accept(self):
        try:
            prob = ProblemDescription(summary=self.summary_ed.toPlainText().strip(),
                                      character=[c for c, cb in self.chars.items() if cb.isChecked()],
                                      receiver=self.receiver_ed.text().strip(), when=self.when_ed.text().strip(),
                                      approx_band_hz=(self.f_lo.value(), self.f_hi.value()) if self.band_on.isChecked() else None)
            taken: set[str] = set()
            eq = []
            for r in range(self.eq_tbl.rowCount()):
                name = (self.eq_tbl.item(r, 0).text() if self.eq_tbl.item(r, 0) else "").strip()
                if not name:
                    continue
                eid = slug(name, taken)
                taken.add(eid)
                eq.append(Equipment(id=eid, name=name, kind=self.eq_tbl.cellWidget(r, 1).currentText()))
            sensors = []
            for r in range(self.s_tbl.rowCount()):
                sid = (self.s_tbl.item(r, 0).text() if self.s_tbl.item(r, 0) else "").strip()
                if not sid:
                    continue
                k = self.s_tbl.cellWidget(r, 1).currentData()
                sensors.append(SensorDescriptor(id=sid, kind=k, quantity=DEFAULT_QUANTITY[k],
                                                model=self.s_tbl.item(r, 2).text() if self.s_tbl.item(r, 2) else ""))
            if len({s.id for s in sensors}) != len(sensors):
                raise ValueError("sensor ids must be unique")
            self.created = self.ctx.app.create_case(self.title_ed.text().strip(), prob, eq, sensors)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Cannot create investigation", str(exc).splitlines()[0])
            return
        super().accept()


class HistoryScreen(QWidget):
    title = "Diagnostic history"

    def __init__(self, ctx: GuiContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.addWidget(h1("Diagnostic history"))
        lay.addWidget(muted("Every diagnosis is kept, so you can see how the hypotheses changed as evidence was added."))
        sp = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("Diagnoses"))
        self.dx_list = QListWidget()
        self.dx_list.currentRowChanged.connect(self.show_dx)
        lv.addWidget(self.dx_list)
        lv.addWidget(QLabel("Procedure runs"))
        self.runs = table(["Procedure", "State", "Step", "Outcome", "Id"], stretch=3)
        lv.addWidget(self.runs)
        lv.addLayout(row(button("Continue selected run", self.resume_run), None))
        sp.addWidget(left)
        right = QWidget()
        rv = QVBoxLayout(right)
        self.dx_text = QPlainTextEdit()
        self.dx_text.setReadOnly(True)
        rv.addWidget(self.dx_text, 1)
        rv.addWidget(QLabel("Activity log"))
        self.log = table(["Time (UTC)", "Action", "Target", "Detail"], stretch=3)
        rv.addWidget(self.log, 1)
        sp.addWidget(right)
        sp.setSizes([420, 700])
        lay.addWidget(sp)
        for s in (ctx.caseChanged, ctx.dataChanged, ctx.diagnosisChanged):
            s.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.dx_list.clear()
        self.dx_text.clear()
        if self.ctx.app.store is None:
            fill_table(self.runs, [])
            fill_table(self.log, [])
            return
        self._dx = self.ctx.app.diagnoses()
        for d in reversed(self._dx):
            top = d.hypotheses[0].statement if d.hypotheses else "-"
            it = QListWidgetItem(f"{d.created_utc:%Y-%m-%d %H:%M}  {d.conclusion.replace('_', ' ')}  |  {top[:60]}")
            self.dx_list.addItem(it)
        from .. import procedures

        rows = []
        for r in reversed(self.ctx.app.runs()):
            p, n = procedures.progress(r)
            rows.append([procedures.get(r.procedure_id).title, r.state, f"{p}/{n}", r.outcome[:80], r.id])
        fill_table(self.runs, rows)
        fill_table(self.log, [[x["ts"][:19].replace("T", " "), x["action"], x["target"], x["detail"][:120]]
                              for x in self.ctx.app.store.audit_log(500)])

    def show_dx(self, i):
        if i < 0 or not getattr(self, "_dx", None):
            return
        d = list(reversed(self._dx))[i]
        lines = [f"Conclusion: {d.conclusion}  (ruleset {d.ruleset_version})"] + [f"  ! {x}" for x in d.abstention_reasons] + [""]
        for h in d.hypotheses:
            lines.append(f"[{h.level.value}] {h.statement}")
        lines += ["", "Evidence:"] + [f"  ({e.statement_class.value}) {e.summary}" for e in d.evidence]
        self.dx_text.setPlainText("\n".join(lines))

    def resume_run(self):
        r = self.runs.currentRow()
        if r < 0:
            return
        self.ctx.runSelected.emit(self.runs.item(r, 4).text())
        self.ctx.navigate.emit("guided")



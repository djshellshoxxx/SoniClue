"""GUI infrastructure: theme, shared context, worker bridge, small widgets.

Threading rule: the GUI thread never runs analysis, I/O-heavy work or device
waits. ``GuiContext.run`` submits work to the app JobRunner and delivers the
result through a Qt signal (queued connection), so callbacks run on the GUI
thread.
"""

from __future__ import annotations

import traceback
from typing import Callable

import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from ..app.service import CaptureSpec, SonicClueApp
from ..domain.model import CaptureContext, ChannelConfig, Mounting, Placement

# Circuit Drift Labs palette
BG = "#0d1420"
PANEL = "#152033"
PANEL2 = "#1c2a40"
BORDER = "#2a3b55"
TEXT = "#e6edf3"
MUTED = "#8b9bb4"
ACCENT = "#3fa7ff"
OK = "#3fbf7f"
WARN = "#e3b341"
BAD = "#f85149"
LEVEL_COLOR = {"strongly_supported": OK, "supported": "#7cc4ff", "undetermined": MUTED, "weakened": WARN, "contradicted": BAD}
CLASS_COLOR = {"measured": "#58a6ff", "calculated": "#3fbf7f", "inferred": "#e3b341", "user_asserted": "#bc8cff", "unresolved": "#f85149"}
PLOT_COLORS = ["#58a6ff", "#f0883e", "#3fbf7f", "#bc8cff", "#e3b341", "#ff7b72"]

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QFrame#panel, QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; }}
QGroupBox {{ margin-top: 14px; padding: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QPushButton {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #556; border-color: #233; }}
QPushButton#primary {{ background: #1f5f99; border-color: {ACCENT}; font-weight: 600; }}
QPushButton#danger {{ background: #5a1d1d; border-color: {BAD}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{ background: #0b111b; border: 1px solid {BORDER};
    border-radius: 4px; padding: 3px; selection-background-color: #1f5f99; }}
QTableWidget, QTreeWidget, QListWidget {{ background: #0b111b; border: 1px solid {BORDER}; gridline-color: {BORDER};
    alternate-background-color: #101827; }}
QHeaderView::section {{ background: {PANEL2}; color: {MUTED}; border: none; padding: 4px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {PANEL}; padding: 6px 12px; border: 1px solid {BORDER}; }}
QTabBar::tab:selected {{ background: {PANEL2}; color: {ACCENT}; }}
QListWidget#nav {{ background: {PANEL}; border: none; font-size: 10.5pt; }}
QListWidget#nav::item {{ padding: 9px 10px; }}
QListWidget#nav::item:selected {{ background: #1f3a5f; color: white; border-left: 3px solid {ACCENT}; }}
QProgressBar {{ border: 1px solid {BORDER}; border-radius: 3px; text-align: center; background: #0b111b; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {ACCENT}; }}
QLabel#h1 {{ font-size: 15pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, col in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, "#0b111b"), (QPalette.Text, TEXT),
                      (QPalette.Button, PANEL2), (QPalette.ButtonText, TEXT), (QPalette.Highlight, "#1f5f99"),
                      (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, PANEL2), (QPalette.ToolTipText, TEXT)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)
    pg.setConfigOptions(background="#0b111b", foreground="#c9d1d9", antialias=False)


class _Bridge(QObject):
    done = Signal(object, object, object)  # callback, result, error


class GuiContext(QObject):
    caseChanged = Signal()
    dataChanged = Signal()
    diagnosisChanged = Signal()
    modeChanged = Signal(str)
    status = Signal(str)
    navigate = Signal(str)
    runSelected = Signal(str)

    def __init__(self, app: SonicClueApp):
        super().__init__()
        self.app = app
        self.mode = app.settings.get("mode", "guided")
        self._bridge = _Bridge()
        self._bridge.done.connect(self._deliver, Qt.QueuedConnection)
        self.busy = 0
        self.base_spec = self.default_spec()

    # ---------------- capture configuration shared by Live and Guided screens ----------------
    def default_spec(self) -> CaptureSpec:
        backend = self.app.settings.get("backend", "portaudio")
        try:
            self.app.backend(backend)
        except Exception:  # noqa: BLE001 - no PortAudio: fall back to the simulator
            backend = "simulated"
        return CaptureSpec(channels=[ChannelConfig(index=0, label="mic", agc="unknown", placement=Placement(position_id="P1",
                                                                                                          mounting=Mounting.STAND))],
                           duration_s=15.0, backend=backend, device=self.app.settings.get("device") if backend != "simulated" else 0,
                           samplerate=float(self.app.settings.get("samplerate", 48000)), context=CaptureContext())

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.app.save_settings(mode=mode)
        self.modeChanged.emit(mode)

    @property
    def expert(self) -> bool:
        return self.mode == "expert"

    # ---------------- jobs ----------------
    def run(self, fn: Callable, on_done: Callable | None = None, on_error: Callable | None = None, label: str = "") -> None:
        """Run ``fn(cancel)`` on a worker thread; deliver the result on the GUI thread."""
        self.busy += 1
        if label:
            self.status.emit(label + " ...")

        def job(cancel):
            return fn(cancel)

        fut, _tok = self.app.jobs.submit(job)

        def cb(f):
            err = f.exception()
            res = None if err else f.result()
            self._bridge.done.emit((on_done, on_error, label), res, err)

        fut.add_done_callback(cb)

    def _deliver(self, cbs, res, err) -> None:
        on_done, on_error, label = cbs
        self.busy = max(0, self.busy - 1)
        if err is not None:
            msg = getattr(err, "message", None) or str(err)
            code = getattr(err, "code", type(err).__name__)
            self.status.emit(f"{label or 'task'} failed: {msg}")
            if on_error:
                on_error(err)
            else:
                error_box(None, f"{label or 'Operation'} failed", f"[{code}] {msg}",
                          "".join(traceback.format_exception(type(err), err, err.__traceback__))[-2000:])
            return
        if label:
            self.status.emit(f"{label}: done")
        if on_done:
            on_done(res)

    def require_case(self, parent) -> bool:
        if self.app.store is None:
            QMessageBox.information(parent, "No investigation open", "Open or create an investigation on the Case dashboard first.")
            return False
        return True


def error_box(parent, title: str, text: str, details: str = "") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if details:
        box.setDetailedText(details)
    box.exec()


def confirm(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes


def h1(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("h1")
    return lab


def muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


def button(text: str, slot=None, kind: str = "", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setAccessibleName(text)
    return b


def panel(layout=None) -> QFrame:
    f = QFrame()
    f.setObjectName("panel")
    f.setLayout(layout or QVBoxLayout())
    return f


def row(*widgets, stretch_last=False) -> QHBoxLayout:
    lay = QHBoxLayout()
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    if stretch_last:
        lay.addStretch(1)
    return lay


def table(columns: list[str], stretch: int | None = None) -> QTableWidget:
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch is not None:
        hh.setSectionResizeMode(stretch, QHeaderView.Stretch)
    return t


def fill_table(t: QTableWidget, rows: list[list], colors: list[str | None] | None = None) -> None:
    t.setRowCount(0)
    for i, r in enumerate(rows):
        t.insertRow(i)
        for j, v in enumerate(r):
            it = QTableWidgetItem("" if v is None else str(v))
            if colors and colors[i]:
                it.setForeground(QColor(colors[i]))
            t.setItem(i, j, it)


def combo(items: list[tuple[str, object]], current=None) -> QComboBox:
    c = QComboBox()
    for text, data in items:
        c.addItem(text, data)
    if current is not None:
        idx = c.findData(current)
        if idx >= 0:
            c.setCurrentIndex(idx)
    return c


def badge(text: str, color: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"background:{color}; color:#0b111b; border-radius:3px; padding:1px 6px; font-weight:600;")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    return lab


class LevelMeter(QWidget):
    """Horizontal peak meter, -80..0 dBFS, with a clip lamp."""

    def __init__(self, label: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.name = QLabel(label)
        self.name.setMinimumWidth(70)
        self.bar = QProgressBar()
        self.bar.setRange(-80, 0)
        self.bar.setTextVisible(True)
        self.bar.setAccessibleName(f"level meter {label}")
        self.clip = QLabel("CLIP")
        self.clip.setStyleSheet(f"color:{MUTED}; font-weight:600;")
        lay.addWidget(self.name)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.clip)

    def set(self, peak_db: float, clipped: bool) -> None:
        v = int(max(-80, min(0, peak_db)))
        self.bar.setValue(v)
        self.bar.setFormat(f"{peak_db:.1f} dBFS")
        color = BAD if peak_db > -1 else (WARN if peak_db > -6 else ACCENT)
        self.bar.setStyleSheet(f"QProgressBar::chunk{{background:{color};}}")
        self.clip.setStyleSheet(f"color:{BAD if clipped else MUTED}; font-weight:600;")


def log_plot(title: str, ylabel: str) -> pg.PlotWidget:
    w = pg.PlotWidget(title=title)
    w.setLogMode(x=True, y=False)
    w.showGrid(x=True, y=True, alpha=0.25)
    w.setLabel("bottom", "Frequency", units="Hz")
    w.setLabel("left", ylabel)
    w.addLegend(offset=(10, 10))
    w.getAxis("bottom").enableAutoSIPrefix(False)
    return w


def single_shot(ms: int, fn) -> None:
    QTimer.singleShot(ms, fn)

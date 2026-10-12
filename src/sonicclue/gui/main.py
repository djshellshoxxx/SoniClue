"""SonicClue desktop GUI entry point: main window with 12 screens.

Keyboard: Ctrl+1..Ctrl+9, Ctrl+0, Ctrl+- and Ctrl+= switch screens; Ctrl+N
starts a new investigation; Esc stops any test signal immediately; F1 opens
help.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
    QComboBox,
)

from .. import __version__
from ..app.service import SonicClueApp
from .common import GuiContext, apply_theme
from .screens_case import DashboardScreen, HistoryScreen
from .screens_dx import GuidedScreen, HypothesesScreen, ReportScreen
from .screens_measure import AnalysisScreen, CompareScreen, LiveScreen
from .screens_setup import CalibrationScreen, DevicesScreen, SettingsScreen

SCREENS = [
    ("dashboard", DashboardScreen), ("devices", DevicesScreen), ("calibration", CalibrationScreen), ("live", LiveScreen),
    ("analysis", AnalysisScreen), ("hypotheses", HypothesesScreen), ("guided", GuidedScreen), ("compare", CompareScreen),
    ("history", HistoryScreen), ("report", ReportScreen), ("settings", SettingsScreen),
]
KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-"]


class MainWindow(QMainWindow):
    def __init__(self, app: SonicClueApp):
        super().__init__()
        self.ctx = GuiContext(app)
        self.setWindowTitle(f"SonicClue {__version__} - Circuit Drift Labs")
        self.resize(1360, 860)
        self.setMinimumSize(1024, 680)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(210)
        self.nav.setAccessibleName("screens")
        self.stack = QStackedWidget()
        self.keys: dict[str, int] = {}
        for i, (key, cls) in enumerate(SCREENS):
            w = cls(self.ctx)
            self.stack.addWidget(w)
            self.nav.addItem(f"{w.title}")
            self.nav.item(i).setToolTip(f"Ctrl+{KEYS[i]}")
            self.keys[key] = i
            QShortcut(QKeySequence(f"Ctrl+{KEYS[i]}"), self, activated=lambda i=i: self.nav.setCurrentRow(i))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.case_lbl = QLabel("")
        self.mode = QComboBox()
        self.mode.addItem("Guided mode", "guided")
        self.mode.addItem("Expert mode", "expert")
        self.mode.setCurrentIndex(0 if self.ctx.mode == "guided" else 1)
        self.mode.currentIndexChanged.connect(lambda: self.ctx.set_mode(self.mode.currentData()))
        self.mode.setAccessibleName("mode")
        sb.addPermanentWidget(self.case_lbl)
        sb.addPermanentWidget(self.mode)
        self.ctx.status.connect(lambda m: sb.showMessage(m, 8000))
        self.ctx.navigate.connect(lambda k: self.nav.setCurrentRow(self.keys.get(k, 0)))
        self.ctx.caseChanged.connect(self.update_case)
        QShortcut(QKeySequence("Escape"), self, activated=self.stop_output)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: (self.nav.setCurrentRow(0), self.stack.widget(0).new_case()))
        QShortcut(QKeySequence("F1"), self, activated=self.help)
        self.update_case()

    def update_case(self):
        st = self.ctx.app.store
        self.case_lbl.setText(f"Case: {st.case.title}" if st else "No case open")
        self.ctx.base_spec = self.ctx.base_spec  # keep configuration across cases

    def stop_output(self):
        self.ctx.app.output.stop()
        self.statusBar().showMessage("Output stopped and disarmed", 4000)

    def help(self):
        QMessageBox.information(self, "SonicClue help", "Typical workflow:\n1. Case dashboard: create an investigation.\n2. Devices: choose "
                                "the interface, describe each channel (sensor, position, gain, AGC off).\n3. Guided tests: run 'Baseline', "
                                "then the tests SonicClue recommends.\n4. Hypotheses: update the diagnosis; read the supporting and "
                                "conflicting evidence.\n5. Report builder: export the evidence.\n\nEsc stops any test signal. "
                                "See docs/USER_GUIDE.md for details.")

    def closeEvent(self, e):  # noqa: N802
        live = self.stack.widget(self.keys["live"])
        if getattr(live, "handle", None) is not None and live.handle.state.value == "running":
            if QMessageBox.question(self, "Recording in progress", "Stop the recording (keeping the data) and quit?") != QMessageBox.Yes:
                e.ignore()
                return
            live.handle.stop()
            live.handle.finalize(timeout=10)
        self.ctx.app.shutdown()
        e.accept()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    qt = QApplication.instance() or QApplication(argv)
    qt.setApplicationName("SonicClue")
    qt.setOrganizationName("Circuit Drift Labs")
    qt.setAttribute(Qt.AA_DontShowIconsInMenus, True)
    apply_theme(qt)
    ws = None
    if "--workspace" in argv:
        ws = Path(argv[argv.index("--workspace") + 1])
    try:
        app = SonicClueApp(ws)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "SonicClue cannot start", f"{exc}")
        return 2
    w = MainWindow(app)
    w.show()
    if "--smoke-test" in argv:  # packaging check: build every screen, then quit
        for i in range(w.nav.count()):
            w.nav.setCurrentRow(i)
            qt.processEvents()
        w.close()
        print(f"SonicClue GUI smoke test OK ({w.nav.count()} screens)")
        return 0
    return qt.exec()



if __name__ == "__main__":
    sys.exit(main())

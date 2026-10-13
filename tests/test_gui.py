"""GUI smoke and wiring tests (offscreen Qt). Run with QT_QPA_PLATFORM=offscreen.

They drive real screens through their controls, so a regression in wiring
(e.g. a button calling a removed method) fails here.
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytestmark = pytest.mark.gui

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from sonicclue.app.service import SonicClueApp  # noqa: E402
from sonicclue.domain.model import Equipment, ProblemDescription, SensorDescriptor, SensorKind  # noqa: E402
from sonicclue.domain.units import Quantity  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(qapp, cond, timeout=60.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    from sonicclue.gui import common
    from sonicclue.gui.main import MainWindow

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(common, "confirm", lambda *a, **k: True)
    errors = []
    monkeypatch.setattr(common, "error_box", lambda parent, title, text, details="": errors.append((title, text)))
    for mod in ("screens_case", "screens_setup", "screens_measure", "screens_dx"):
        m = __import__(f"sonicclue.gui.{mod}", fromlist=["x"])
        monkeypatch.setattr(m, "confirm", lambda *a, **k: True, raising=False)
        monkeypatch.setattr(m, "error_box", lambda parent, title, text, details="": errors.append((title, text)), raising=False)
    app = SonicClueApp(tmp_path, sim_speed=40)
    w = MainWindow(app)
    w.errors = errors
    w.show()
    yield w
    w.close()


def test_all_screens_construct_and_switch(window, qapp):
    for i in range(window.nav.count()):
        window.nav.setCurrentRow(i)
        qapp.processEvents()
        assert window.stack.currentIndex() == i
    assert window.nav.count() == 11
    window.ctx.set_mode("expert")
    qapp.processEvents()
    window.ctx.set_mode("guided")
    assert not window.errors


def test_capture_analysis_guided_and_report_flow(window, qapp, tmp_path):
    app = window.ctx.app
    app.create_case("gui flow", ProblemDescription(summary="hum"), [Equipment(id="pc", name="PC", kind="computer")],
                    [SensorDescriptor(id="mic1", kind=SensorKind.STUDIO_MIC, quantity=Quantity.SOUND_PRESSURE)])
    window.ctx.caseChanged.emit()
    qapp.processEvents()
    # Devices screen: switch to simulator, apply
    dev = window.stack.widget(window.keys["devices"])
    dev.backend.setCurrentIndex(dev.backend.findData("simulated"))
    qapp.processEvents()
    dev.ch.cellWidget(0, 7).setCurrentIndex(dev.ch.cellWidget(0, 7).findData("off"))
    dev.apply()
    assert window.ctx.base_spec.backend == "simulated"
    assert window.ctx.base_spec.channels[0].sensor_id == "mic1"
    # Live screen: record 3 s
    live = window.stack.widget(window.keys["live"])
    window.nav.setCurrentRow(window.keys["live"])
    live.dur.setValue(3)
    live.label.setText("baseline")
    live.start()
    assert live.handle is not None
    assert pump(qapp, lambda: live.handle is None and len(app.captures()) == 1, 60)
    assert app.captures()[0].context.condition_label == "baseline"
    # Analysis screen shows it
    an = window.stack.widget(window.keys["analysis"])
    window.nav.setCurrentRow(window.keys["analysis"])
    an.refresh()
    assert pump(qapp, lambda: an.cur is not None, 60)
    assert "tier" in an.summary.toPlainText()
    # Guided: baseline procedure end-to-end
    g = window.stack.widget(window.keys["guided"])
    g.lib.setCurrentRow([d.id for d in g._lib].index("baseline"))
    g.start()
    assert g.run_id
    g.act_step()  # instruction
    for _ in range(2):
        g.act_step()  # record
        assert pump(qapp, lambda: g.handle is None and not g.timer.isActive() and window.ctx.busy == 0, 60)
    assert app.run(g.run_id).state == "completed"
    # Hypotheses
    hy = window.stack.widget(window.keys["hypotheses"])
    hy.run()
    assert pump(qapp, lambda: app.latest_diagnosis() is not None and hy.tree.topLevelItemCount() > 0, 30)
    # Report export
    rep = window.stack.widget(window.keys["report"])
    rep.preview()
    assert pump(qapp, lambda: "SonicClue investigation report" in rep.view.toHtml(), 60)
    out = app.export_report("html", tmp_path / "r.html")
    assert out.exists()
    assert not window.errors, window.errors


def test_output_escape_stops(window, qapp):
    app = window.ctx.app
    app.arm_output(0, backend="simulated", confirmed=True, level_limit_dbfs=-30, max_duration_s=5)
    from sonicclue.domain.model import StimulusRecord

    app.output.play(StimulusRecord(kind="sine", level_dbfs=-30, params={"freq": 440}), 5)
    assert app.output.state.value == "playing"
    window.stop_output()
    assert app.output.state.value == "disarmed"

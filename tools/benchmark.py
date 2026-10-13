#!/usr/bin/env python3
"""Reproducible benchmarks (docs/specs/16-performance.md).

    python tools/benchmark.py [--out docs/specs/research/benchmark-<host>.json] [--quick]

Each metric runs in a fresh subprocess so peak RSS is attributable. Results
include the machine description. Never publish numbers from a different
machine as reference-hardware results.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SNIPPETS = {
    "import_core": "T0=time.perf_counter()\nimport sonicclue.app.service\nRESULT=time.perf_counter()-T0",
    "analysis_60s_2ch": """
import numpy as np
from sonicclue.analysis.pipeline import analyze
from sonicclue.domain.model import *
from sonicclue.dsp import signals
fs=48000.; n=int(60*fs)
x=np.stack([signals.white_noise(0.05,60,fs,seed=1)+signals.sine(117,0.1,60,fs), signals.white_noise(0.02,60,fs,seed=2)],1).astype('float32')
m=CaptureManifest(id='cap-bench01',case_id='c',created_utc=utcnow(),source='live',device=DeviceInfo(backend='file'),sample_rate_hz=fs,
  channels=[ChannelConfig(index=0,label='a'),ChannelConfig(index=1,label='b')],frames=n,clock_domain='x',software_version='b')
T0=time.perf_counter(); analyze(m,x,{},{}); RESULT=time.perf_counter()-T0
""",
    "analysis_600s_2ch": """
import numpy as np
from sonicclue.analysis.pipeline import analyze
from sonicclue.domain.model import *
from sonicclue.dsp import signals
fs=48000.; n=int(600*fs)
x=np.empty((n,2),np.float32)
for i in range(10):  # build the fixture in float32 chunks so its own footprint does not dominate peak RSS
    x[i*int(60*fs):(i+1)*int(60*fs),0]=signals.white_noise(0.05,60,fs,seed=1+i)
    x[i*int(60*fs):(i+1)*int(60*fs),1]=signals.white_noise(0.02,60,fs,seed=100+i)
m=CaptureManifest(id='cap-bench02',case_id='c',created_utc=utcnow(),source='live',device=DeviceInfo(backend='file'),sample_rate_hz=fs,
  channels=[ChannelConfig(index=0,label='a'),ChannelConfig(index=1,label='b')],frames=n,clock_domain='x',software_version='b')
T0=time.perf_counter(); analyze(m,x,{},{}); RESULT=time.perf_counter()-T0
""",
    "writer_throughput_MBps": """
import numpy as np, tempfile, pathlib
from sonicclue.storage.writer import CaptureWriter
d=pathlib.Path(tempfile.mkdtemp())/'c'
w=CaptureWriter(d,'cap-x',48000,8,{})
blk=np.random.default_rng(0).standard_normal((1024,8)).astype('float32')
T0=time.perf_counter()
for i in range(48000*60//1024): w.write(blk)
w.close(); dt=time.perf_counter()-T0
RESULT=(48000*60*8*4/1e6)/dt
""",
    "capture_sim_30s_realtime_cpu_pct": """
import resource, tempfile, pathlib
from sonicclue.app.service import SonicClueApp, CaptureSpec
from sonicclue.domain.model import ChannelConfig, CaptureContext
app=SonicClueApp(pathlib.Path(tempfile.mkdtemp()), sim_speed=1.0)
app.create_case('b')
r0=resource.getrusage(resource.RUSAGE_SELF); T0=time.perf_counter()
app.capture_blocking(CaptureSpec(channels=[ChannelConfig(index=i,label=f'c{i}') for i in range(3)],duration_s=30,backend='simulated',device=0))
r1=resource.getrusage(resource.RUSAGE_SELF); wall=time.perf_counter()-T0
# includes the simulator's own synthesis cost: an upper bound for the acquisition path
RESULT=100*((r1.ru_utime+r1.ru_stime)-(r0.ru_utime+r0.ru_stime))/wall
app.shutdown()
""",
    "case_open_30_captures": """
import tempfile, pathlib, numpy as np, soundfile as sf
from sonicclue.app.service import SonicClueApp
ws=pathlib.Path(tempfile.mkdtemp()); app=SonicClueApp(ws)
cid=app.create_case('b')
p=ws/'x.wav'; sf.write(p, np.zeros((48000*5,2),'float32'), 48000, subtype='FLOAT')
for i in range(30): app.import_audio(p)
app.close_case()
T0=time.perf_counter(); app.open_case(cid); caps=app.captures(); RESULT=time.perf_counter()-T0
app.shutdown()
""",
    "demo_report_html_pdf": """
import tempfile, pathlib
from sonicclue.app.service import SonicClueApp
from sonicclue.app.demo import run_demo
app=SonicClueApp(pathlib.Path(tempfile.mkdtemp()), sim_speed=80)
run_demo(app, progress=lambda m: None, duration_scale=0.4)
T0=time.perf_counter(); app.export_report('html'); app.export_report('pdf'); RESULT=time.perf_counter()-T0
app.shutdown()
""",
    "diagnose_demo_case": """
import tempfile, pathlib
from sonicclue.app.service import SonicClueApp
from sonicclue.app.demo import run_demo
app=SonicClueApp(pathlib.Path(tempfile.mkdtemp()), sim_speed=80)
run_demo(app, progress=lambda m: None, duration_scale=0.4)
T0=time.perf_counter(); app.diagnose(); RESULT=time.perf_counter()-T0
app.shutdown()
""",
    "archive_roundtrip_100MB": """
import tempfile, pathlib, numpy as np, soundfile as sf
from sonicclue.app.service import SonicClueApp
ws=pathlib.Path(tempfile.mkdtemp()); app=SonicClueApp(ws)
cid=app.create_case('b')
p=ws/'x.wav'; sf.write(p, (np.random.default_rng(1).standard_normal((48000*130,2))*0.1).astype('float32'), 48000, subtype='FLOAT')
app.import_audio(p)
T0=time.perf_counter(); app.export_archive(ws/'a.scarchive'); app.close_case()
app2=SonicClueApp(pathlib.Path(tempfile.mkdtemp())); app2.import_archive(ws/'a.scarchive'); RESULT=time.perf_counter()-T0
app.shutdown(); app2.shutdown()
""",
    "gui_idle_rss_MB": """
import os; os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile, pathlib, resource
from PySide6.QtWidgets import QApplication
qa=QApplication([])
from sonicclue.app.service import SonicClueApp
from sonicclue.gui.main import MainWindow
w=MainWindow(SonicClueApp(pathlib.Path(tempfile.mkdtemp()))); w.show(); qa.processEvents()
RESULT=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
""",
}

RUNNER = """
import time, resource, json, sys
{code}
print(json.dumps({{"value": RESULT, "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024}}))
"""


def machine() -> dict:
    info = {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(), "machine": platform.machine()}
    try:
        info["cpu"] = next(line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo") if line.startswith("model name"))
        info["mem_gb"] = round(int(next(line.split()[1] for line in open("/proc/meminfo") if line.startswith("MemTotal"))) / 1e6, 1)
    except (OSError, StopIteration):
        pass
    return info


def main() -> int:
    out = None
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
    quick = "--quick" in sys.argv
    results = {}
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    for name, code in SNIPPETS.items():
        if quick and name in ("analysis_600s_2ch", "archive_roundtrip_100MB", "capture_sim_30s_realtime_cpu_pct"):
            continue
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, "-c", RUNNER.format(code=code)], capture_output=True, text=True, env=env, cwd=tempfile.gettempdir())
        wall = time.perf_counter() - t0
        if r.returncode != 0:
            results[name] = {"error": r.stderr.strip().splitlines()[-1] if r.stderr else "failed"}
        else:
            d = json.loads(r.stdout.strip().splitlines()[-1])
            d["process_wall_s"] = round(wall, 2)
            results[name] = d
        print(f"{name:<36} {results[name]}")
    doc = {"machine": machine(), "results": results, "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# 16 Performance and resources

Benchmarks: `tools/benchmark.py` (each metric in a fresh subprocess; peak RSS from `getrusage`). Raw results: `research/benchmark-build-vm.json`.

## 1 Reference hardware (DEC-002)

* **Minimum:** x86-64 dual-core CPU (2015 or newer), 4 GB RAM, 1 GB free disk plus recordings (0.69 GB per channel-hour), 1366×768 display, no dedicated GPU, Windows 11 x64 (Windows 10 22H2 best-effort) or Ubuntu 22.04+/glibc ≥ 2.35.
* **Reference machine for acceptance:** a typical office Windows 11 desktop (4-core x64, 8 GB RAM, SATA SSD) to be designated by the owner (**VALIDATION_REQUIRED**). The numbers below come from the **build VM** (Linux, 4 vCPU, 15 GB). They are *not* reference-hardware results.

## 2 Budgets, method and measured results (build VM)

| Metric | Budget (reference machine) | How measured | Build VM result | Status |
|---|---|---|---|---|
| Core import (startup cost) | ≤ 3 s | `import_core` | 1.40 s, 142 MB | met on VM |
| Idle GUI memory | ≤ 400 MB | `gui_idle_rss_MB` (offscreen) | 278 MB | met on VM |
| Analysis 60 s × 2 ch @ 48 kHz | ≤ 10 s, ≤ 600 MB | `analysis_60s_2ch` | 1.88 s, 305 MB | met on VM |
| Analysis 600 s × 2 ch @ 48 kHz | ≤ 60 s, ≤ 1.5 GB | `analysis_600s_2ch` | 17.9 s, 926 MB | met on VM |
| Capture disk throughput | ≥ 10 MB/s (8 ch × 48 kHz float32 = 1.5 MB/s, ≥ 6× margin) | `writer_throughput_MBps` | 267 MB/s | met on VM |
| Live capture CPU (3 ch simulated, includes synthesis) | ≤ 25% of one core | `capture_sim_30s_realtime_cpu_pct` | 20% (upper bound: includes simulator synthesis) | met on VM |
| Capture latency (device → disk) | ≤ 15 s (one chunk) | design: 10 s chunks + queue | by design | – |
| Live display refresh | ≥ 5 Hz | GUI timer 100 ms | 10 Hz timer | by design |
| Case open (30 captures) | ≤ 2 s | `case_open_30_captures` | 0.005 s | met on VM |
| Diagnosis (demo case, 17 captures) | ≤ 2 s | `diagnose_demo_case` | 0.11 s | met on VM |
| Report HTML+PDF (demo case) | ≤ 30 s | `demo_report_html_pdf` | 6.5 s | met on VM |
| Archive export + import 100 MB | ≤ 60 s | `archive_roundtrip_100MB` | 4.9 s | met on VM |
| Analysis 60 min × 2 ch @ 48 kHz (spooled) | ≤ 1.5 GB resident, results identical to in-memory | `analysis_60min_2ch_spooled` | 115 s, 1.21 GB (build VM) | met on VM |
| Long sessions | 4 h live capture; full-length analysis up to `max_analysis_seconds` (default 14400) | design + section 5 | – | TASK-012 implemented |
| 8-ch 1-h capture without dropouts | 0 gaps | hardware test HQ-03 | **UNEXECUTED** (no hardware) | VALIDATION_REQUIRED |

## 3 Optimisation record (profiling evidence)

| Bottleneck | Evidence | Change | Result | Correctness check |
|---|---|---|---|---|
| Memory in long analyses | 600 s × 2 ch peaked at 3.27 GB (25.4 s); per-stage tracemalloc: Welch 460 MB, spectrogram 461 MB, envelope 576 MB, screening 389 MB per 300 s mono | block-wise Welch/CSD (64 segments), bounded-frame spectrogram, 20 s envelope blocks, chunked screening/level/event passes, float32 channel buffers | **0.93 GB (-72%), 17.9 s (-30%)** | `test_blocked_welch_equals_single_call` (rtol 1e-10), `test_spectrogram_matches_scipy_reference`, full suite |

No native code was introduced. Remaining hotspots on the VM: Welch FFTs (expected) and the envelope Hilbert transform. Neither currently justifies further work.

## 5 Full-length analysis (TASK-012, REQ-PERF-001)

**Requirement.** Analysis of captures longer than 600 s shall not hold the capture in RAM: peak resident memory for a 60-minute 2-channel 48 kHz capture is ≤ 1.5 GB, and every result equals the in-memory result (exactly; arrays within rtol 1e-9).

**Design.** `analysis/spool.py::ChannelSpool` reads the capture in 2^20-frame blocks (via a loader callable, so `analysis` does not depend on `storage`) into one float32 memory-mapped file per channel under `<case>/derived/.sc-spool-*`. `analyze()` accepts the spool in place of an array and runs the identical code path (all kernels already operate on bounded chunks: block-wise Welch/CSD, chunked screening, level and event passes, 20 s envelope blocks, bounded-frame spectrogram). Sanitising and calibration scaling run in place in chunks. The clip-guard exclusion uses merged intervals instead of full-length cumulative sums. The spool is private to one run and deleted on exit, including on error or cancel.

**Rules.** The app spools when the analysed span exceeds `SPOOL_ABOVE_S` (600 s). Free disk space of at least 1.1× the spool size is required, otherwise `AnalysisError` (nothing is written). Spans beyond `max_analysis_seconds` are truncated and flagged `PARTIAL_CAPTURE` as before. Residual full-length allocations: one bool valid mask per channel (1 byte/sample); output arrays are display-bounded.

**Tests.** `tests/test_spool_analysis.py` (equality with and without clipping/NaN, source untouched, cleanup on success/failure, block-shape check, disk-space check, clip-guard equivalence to the naive definition). Benchmark: `analysis_60min_2ch_spooled`.

## 4 GPU

None used or required. Plots use pyqtgraph's raster path with antialiasing off. Spectrograms are decimated to ≤ 600 frames before display.

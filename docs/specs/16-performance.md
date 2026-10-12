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
| Long sessions | 4 h live capture; analysis of the first 600 s by default (`max_analysis_seconds`) | design | – | streamed full-length analysis is backlog (TASK-012) |
| 8-ch 1-h capture without dropouts | 0 gaps | hardware test HQ-03 | **UNEXECUTED** (no hardware) | VALIDATION_REQUIRED |

## 3 Optimisation record (profiling evidence)

| Bottleneck | Evidence | Change | Result | Correctness check |
|---|---|---|---|---|
| Memory in long analyses | 600 s × 2 ch peaked at 3.27 GB (25.4 s); per-stage tracemalloc: Welch 460 MB, spectrogram 461 MB, envelope 576 MB, screening 389 MB per 300 s mono | block-wise Welch/CSD (64 segments), bounded-frame spectrogram, 20 s envelope blocks, chunked screening/level/event passes, float32 channel buffers | **0.93 GB (-72%), 17.9 s (-30%)** | `test_blocked_welch_equals_single_call` (rtol 1e-10), `test_spectrogram_matches_scipy_reference`, full suite |

No native code was introduced. Remaining hotspots on the VM: Welch FFTs (expected) and the envelope Hilbert transform. Neither currently justifies further work.

## 4 GPU

None used or required. Plots use pyqtgraph's raster path with antialiasing off. Spectrograms are decimated to ≤ 600 frames before display.

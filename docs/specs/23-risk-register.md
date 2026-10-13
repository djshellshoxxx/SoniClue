# 23 Risk and blocker register

CSV form: `matrices/risk-register.csv`. Likelihood/impact: L/M/H.

| ID | Kind | Description | L | I | Owner | Mitigation / resolution | Exit criterion | Status |
|---|---|---|---|---|---|---|---|---|
| RISK-001 | blocker | No audio hardware available in the build environment: every physical device is unqualified | H | H | owner | run HQ-01..09 on target devices | compatibility matrix rows QUALIFIED for the initial device list | OPEN |
| RISK-002 | blocker | Project licence undecided (DEC-009b) | H | M | owner | choose a licence; update LICENSE-NOTICE and package metadata | licence file committed | OPEN |
| RISK-003 | blocker | No code-signing certificate (Windows SmartScreen warnings) | H | M | owner | acquire a certificate; sign in CI | signed artifacts verified | OPEN |
| RISK-004 | risk | Python audio callback (GIL, allocation) may drop blocks on slow machines | M | H | acquisition owner | bounded queue + explicit gaps (implemented); large buffers; fallback: rtmixer C ring buffer (MIT) | HQ-03 passes with 0 gaps on the reference machine | MONITORING |
| RISK-005 | risk | Diagnostic thresholds tuned only on synthetic data | H | H | diagnostics owner | conservative abstention; ordinal levels; tuning/held-out protocol (spec 17 section 6) | held-out evaluation reported | OPEN |
| RISK-006 | risk | Windows AGC/"enhancements" alter levels silently | M | H | product | AGC field mandatory for comparisons; exclusive-mode option; guidance in the user guide | HQ-02 with enhancements on/off documented | MITIGATED (software) |
| RISK-007 | risk | Contact pickup readings misread as calibrated vibration | M | M | product | relative-only enforcement; airborne-control procedure; labels | – | MITIGATED |
| RISK-008 | risk | Long captures exceed memory on 4 GB machines | M | M | dsp owner | block-wise analysis; analysis limited to the first 600 s by default; streamed analysis backlog | TASK-012 done | PARTIALLY MITIGATED |
| RISK-009 | risk | LGPL compliance for Qt/libsndfile in proprietary distribution | L | H | release | onedir build; notices; source offer | legal review | MITIGATED (pending review) |
| RISK-010 | risk | Room modes mislead location surveys at low frequency | M | M | diagnostics | stated in recommendations and in rule limitations | – | ACCEPTED |
| RISK-011 | risk | Bridge board/firmware not selected (MEMS accelerometers) | H | L | owner/hardware | protocol + decoder ready; IEPE-via-audio path documented | board chosen and firmware built | OPEN (DEC-004b) |
| RISK-012 | risk | Competitive claims inaccurate | M | M | product | comparative review before marketing; no uniqueness claims in docs | review recorded | OPEN |
| RISK-013 | risk | CI Windows build untested locally (only through GitHub Actions) | M | M | release | CI smoke stage runs the frozen binaries on Windows | CI artifact smoke test green | see final report |
| RISK-014 | risk | Spec and implementation produced by the same session (reduced independence of review) | M | M | coordinator | independent review agent / human review of specs 08, 09 | external review recorded | OPEN |

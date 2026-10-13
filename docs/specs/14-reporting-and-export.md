# 14 Reporting and evidence export

Code: `src/sonicclue/reporting/builder.py`, `render.py`; app `build_report / export_report`. Tests: `tests/test_workflows.py::test_reports_all_formats_classes_and_redaction`, GUI preview test.

## 1 Report model (CON-014)

`ReportDocument{id, case_id, report_version (increments per case), created_utc, software_version, ruleset_version, redactions[], case_digest, sections[]}`. Section → statements (class, text, refs), tables, figure keys. Every statement carries exactly one class: **MEASURED, CALCULATED, INFERRED, USER_ASSERTED (shown as USER), UNRESOLVED**. All formats render the class visibly.

Sections: Summary (SIMULATED warning when applicable, conclusion, supported hypotheses, abstention reasons) · Problem description (user assertions, equipment, notes) · Sensors, calibration and devices (sensor table, calibration table with uncertainty and validity, device qualification table, capability tiers) · Measurements (captures with flags, channel levels/tones, spectrum figures) · Test methodology (analysis parameters, algorithm and ruleset versions, statistical method, procedures with revisions) · Evidence · Competing hypotheses (ranked table, explanations, open tests) · Before/after comparisons and interventions (deltas with ±95%, comparability issues, intervention records, band-delta figures) · Recommended next tests · Measurement limitations (fixed list plus capture warnings) · Reproduction instructions (software/build, per-capture rate, channel sensor/position/mounting/gain/AGC, equipment states).

## 2 Formats

| Format | Renderer | Notes |
|---|---|---|
| HTML | `render_html` | self-contained (inline CSS, base64 PNG figures), coloured class tags |
| PDF | `render_pdf` (reportlab) | A4, class tags, tables, figures at 150 dpi |
| JSON | `render_json` | ReportDocument per `report.schema.json` |
| CSV | `render_csv_zip` | every report table plus `statements.csv` and per-capture PSD tables (`psd_<capture>_<channel>.csv`) |
| Portable case archive | spec 13 section 7 | full evidence package |

Figures come from stored arrays via matplotlib (Agg, headless) and are annotated with title, axes and units.

## 3 Redaction

Options: names (equipment names, device names), locations (placement text, receiver), serials, notes (problem summary, annotations, intervention descriptions, condition labels). Redacted values become "[redacted]", and the redaction list is recorded in the document. Ids and numbers are kept so the evidence remains checkable. Archives are never redacted; this is stated in the UI.

## 4 Versioning

`report_version` increments per case. Each report is stored as a document and the rendered file is kept under `reports/`. `case_digest` lets a reader confirm that the report matches the case data.

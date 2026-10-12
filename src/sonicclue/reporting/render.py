"""Report renderers: HTML, PDF (reportlab), JSON, CSV (zip of tables)."""

from __future__ import annotations

import base64
import csv
import html
import io
import zipfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..domain.model import ReportDocument, StatementClass, dump_json  # noqa: E402
from .builder import FigureSpec  # noqa: E402

CLASS_LABEL = {
    StatementClass.MEASURED: ("MEASURED", "#1f6feb"),
    StatementClass.CALCULATED: ("CALCULATED", "#2a7f62"),
    StatementClass.INFERRED: ("INFERRED", "#9a6700"),
    StatementClass.USER_ASSERTED: ("USER", "#6e40c9"),
    StatementClass.UNRESOLVED: ("UNRESOLVED", "#cf222e"),
}


def figure_png(spec: FigureSpec, dpi: int = 110) -> bytes:
    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=dpi)
    for label, x, y in spec.series:
        ax.plot(x, y, label=label, linewidth=1.0)
    if spec.logx:
        ax.set_xscale("log")
    ax.set_title(spec.title, fontsize=10)
    ax.set_xlabel(spec.xlabel)
    ax.set_ylabel(spec.ylabel)
    ax.grid(True, which="both", alpha=0.3)
    if len(spec.series) > 1:
        ax.legend(fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def render_html(doc: ReportDocument, figs: dict[str, FigureSpec]) -> bytes:
    e = html.escape
    out = ["<!doctype html><html><head><meta charset='utf-8'><title>SonicClue report</title><style>",
           "body{font-family:Segoe UI,Helvetica,Arial,sans-serif;max-width:1000px;margin:24px auto;color:#1b1f24;line-height:1.45}",
           "h1{color:#0b1e3f;border-bottom:3px solid #0b1e3f}h2{color:#0b1e3f;margin-top:28px}",
           "table{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}td,th{border:1px solid #d0d7de;padding:3px 6px;text-align:left}",
           "th{background:#eef2f7}.tag{display:inline-block;min-width:88px;font-size:10px;font-weight:600;color:#fff;border-radius:3px;"
           "padding:1px 5px;margin-right:6px;text-align:center}.st{margin:3px 0}.meta{color:#57606a;font-size:12px}img{max-width:100%}",
           "</style></head><body>",
           "<h1>SonicClue investigation report</h1>",
           f"<p class='meta'>Report {e(doc.id)} v{doc.report_version} &middot; case {e(doc.case_id)} &middot; {doc.created_utc:%Y-%m-%d %H:%M} UTC "
           f"&middot; SonicClue {e(doc.software_version)} &middot; ruleset {e(doc.ruleset_version)} &middot; digest {doc.case_digest[:16]}"
           + (f" &middot; redacted: {e(', '.join(doc.redactions))}" if doc.redactions else "") + "</p>",
           "<p class='meta'>Statement classes: " + " ".join(
               f"<span class='tag' style='background:{c}'>{n}</span>" for n, c in CLASS_LABEL.values()) + "</p>"]
    for s in doc.sections:
        out.append(f"<h2>{e(s.title)}</h2>")
        for st in s.statements:
            n, c = CLASS_LABEL[st.cls]
            out.append(f"<div class='st'><span class='tag' style='background:{c}'>{n}</span>{e(st.text)}</div>")
        for t in s.tables:
            out.append(f"<h3>{e(t.title)}</h3><table><tr>" + "".join(f"<th>{e(h)}</th>" for h in t.columns) + "</tr>")
            for row in t.rows:
                out.append("<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in row) + "</tr>")
            out.append("</table>")
        for k in s.figures:
            if k in figs:
                b64 = base64.b64encode(figure_png(figs[k])).decode()
                out.append(f"<img alt='{e(figs[k].title)}' src='data:image/png;base64,{b64}'/>")
    out.append("</body></html>")
    return "\n".join(out).encode("utf-8")


def render_pdf(doc: ReportDocument, figs: dict[str, FigureSpec]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=8, leading=10)
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
                            title="SonicClue report", author="SonicClue")
    story = [Paragraph("SonicClue investigation report", ss["Title"]),
             Paragraph(html.escape(f"Report {doc.id} v{doc.report_version} | case {doc.case_id} | {doc.created_utc:%Y-%m-%d %H:%M} UTC | "
                                   f"SonicClue {doc.software_version} | ruleset {doc.ruleset_version} | digest {doc.case_digest[:16]}"
                                   + (f" | redacted: {', '.join(doc.redactions)}" if doc.redactions else "")), small), Spacer(1, 8)]
    for s in doc.sections:
        story.append(Paragraph(html.escape(s.title), ss["Heading2"]))
        for st in s.statements:
            n, c = CLASS_LABEL[st.cls]
            story.append(Paragraph(f"<font color='{c}'><b>[{n}]</b></font> {html.escape(st.text)}", small))
        for t in s.tables:
            story.append(Paragraph(html.escape(t.title), ss["Heading4"]))
            data = [[Paragraph(html.escape(h), small) for h in t.columns]] + \
                   [[Paragraph(html.escape(str(v)), small) for v in row] for row in t.rows[:300]]
            tb = Table(data, repeatRows=1)
            tb.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(tb)
        for k in s.figures:
            if k in figs:
                story.append(Image(io.BytesIO(figure_png(figs[k], dpi=150)), width=17 * cm, height=7.2 * cm))
    pdf.build(story)
    return buf.getvalue()


def render_json(doc: ReportDocument) -> bytes:
    return dump_json(doc).encode("utf-8")


def render_csv_zip(doc: ReportDocument, extra_tables: dict[str, tuple[list[str], list[list]]] | None = None) -> bytes:
    """All report tables plus ``extra_tables`` (e.g. PSD data) as CSV files in a zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        n = 0
        for s in doc.sections:
            for t in s.tables:
                n += 1
                sio = io.StringIO()
                w = csv.writer(sio)
                w.writerow(t.columns)
                w.writerows(t.rows)
                safe = "".join(ch if ch.isalnum() else "_" for ch in t.title.lower())[:40]
                z.writestr(f"{n:02d}_{s.key}_{safe}.csv", sio.getvalue())
        sio = io.StringIO()
        w = csv.writer(sio)
        w.writerow(["section", "class", "statement", "refs"])
        for s in doc.sections:
            for st in s.statements:
                w.writerow([s.key, st.cls.value, st.text, " ".join(st.refs)])
        z.writestr("statements.csv", sio.getvalue())
        for name, (cols, rows) in (extra_tables or {}).items():
            sio = io.StringIO()
            w = csv.writer(sio)
            w.writerow(cols)
            w.writerows(rows)
            z.writestr(f"{name}.csv", sio.getvalue())
    return buf.getvalue()

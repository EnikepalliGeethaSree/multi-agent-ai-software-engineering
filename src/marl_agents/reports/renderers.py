"""Render a ReviewResult as JSON, Markdown or PDF, all from the same structured result."""

from __future__ import annotations

import json
import time
from pathlib import Path
from xml.sax.saxutils import escape

from marl_agents.core.performance import from_result
from marl_agents.core.schemas import ReviewResult, Severity
from marl_agents.core.timing import TimingBreakdown
from marl_agents.reports.sarif import to_sarif
from marl_agents.reports.summary import ReviewSummary, summarize

_SEV_ORDER = [s.value for s in Severity]


def to_json(result: ReviewResult) -> str:
    payload = {
        "summary": summarize(result).model_dump(),
        "result": json.loads(result.model_dump_json()),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


MAX_HUNKS_IN_REPORT = 10


def _change_markdown(result: ReviewResult) -> list[str]:
    ch = result.change
    if ch is None:
        return []
    sm = ch.summary
    out = [
        "## Change summary",
        "",
        f"`{sm.base}` → `{sm.head}`: {sm.files_changed} file(s), "
        f"+{sm.lines_added} / -{sm.lines_deleted} lines.",
        "",
    ]
    if sm.narrative:
        out += [sm.narrative, ""]
    if sm.salient:
        out += [f"**Main change:** `{sm.salient}`", ""]
    if sm.impacted_files:
        out += [
            "**Unchanged files that call changed code:** "
            + ", ".join(f"`{f}`" for f in sm.impacted_files),
            "",
        ]
    if sm.symbols:
        out += [
            "| Function | Change | Signature | Callers not updated |",
            "|---|---|---|---:|",
        ]
        for sym in sm.symbols:
            sig = (
                f"`{sym.old_signature}` → `{sym.new_signature}`"
                if sym.signature_changed
                else (f"`{sym.new_signature}`" if sym.new_signature else "-")
            )
            out.append(
                f"| `{sym.file}` {sym.qualname} | {sym.kind} | {sig} | {sym.callers_not_updated} |"
            )
        out.append("")
    if ch.hunks:
        out += ["### Review these hunks first", ""]
        for h in ch.hunks[:MAX_HUNKS_IN_REPORT]:
            out += [
                f"**{h.level.upper()} ({h.score:.0f}/100)** `{h.file}:{h.start_line}-{h.end_line}` "
                f"— {'; '.join(h.reasons)}",
                "",
                "```diff",
                h.patch,
                "```",
                "",
            ]
    return out


def to_markdown(result: ReviewResult, title: str | None = None) -> str:
    title = title or ("Change Review Report" if result.change else "Code Review Report")
    s = summarize(result)
    meta = result.metadata
    out: list[str] = [f"# {title}", ""]
    out += [
        f"- **Files analyzed:** {s.files_analyzed} ({s.lines_analyzed} lines)",
        f"- **Findings:** {s.total_findings}",
        f"- **Model:** {meta.provider}{' / ' + meta.model if meta.model else ''}"
        f" | RAG: {'on' if meta.rag_enabled else 'off'} | mode: {result.stats.get('mode', 'n/a')}",
        "",
    ]
    failed = int(result.stats.get("units_failed", 0) or 0)
    if failed and result.stats.get("mode") != "static_only":
        total = result.stats.get("units_total", failed)
        out += [
            f"> **Partial review:** the LLM could not review {failed} of {total} part(s) "
            "(see Pipeline warnings); those parts have static-analysis findings only.",
            "",
        ]
    out += [
        "## Summary",
        "",
        "| Severity | Count |",
        "|---|---:|",
        *[f"| {sev} | {s.by_severity.get(sev, 0)} |" for sev in _SEV_ORDER],
        "",
        "| Area | Count |",
        "|---|---:|",
        f"| Potential bugs | {s.potential_bugs} |",
        f"| Security issues | {s.security_issues} |",
        f"| Error handling | {s.error_handling_issues} |",
        f"| Maintainability / quality | {s.maintainability_issues} |",
        f"| Testing gaps | {s.testing_gaps} |",
        f"| Documentation | {s.documentation_issues} |",
        "",
    ]
    if s.top_files:
        out += ["**Most affected files:** " + ", ".join(f"`{f}`" for f, _ in s.top_files), ""]
    out += _change_markdown(result)

    out += ["## Findings", ""]
    if not result.findings:
        out += ["No findings above the confidence threshold.", ""]
    for f in result.findings:
        loc = f"{f.file}:{f.start_line}" + (f"-{f.end_line}" if f.end_line != f.start_line else "")
        out += [
            f"### {f.id} [{f.severity.value.upper()}] {_md_escape(f.title)}",
            "",
            f"- **Location:** `{loc}`" + (f" in `{f.symbol}`" if f.symbol else ""),
            f"- **Category:** {f.category.value}"
            + (f" | **CWE:** {f.cwe}" if f.cwe else "")
            + (f" | **Rule:** {f.rule_id}" if f.rule_id else ""),
            f"- **Sources:** {', '.join(x.value for x in f.sources)} "
            f"| **Confidence:** {f.confidence:.2f}",
            "",
            f.description,
            "",
        ]
        if f.evidence:
            out += ["**Evidence**", "", "```python", *[e for e in f.evidence[:3]], "```", ""]
        if f.related:
            out += ["**Related:** " + "; ".join(f"`{r}`" for r in f.related), ""]
        if f.recommendation:
            out += [f"**Fix:** {f.recommendation}", ""]
        if f.suggested_fix:
            fx = f.suggested_fix
            badge = "verified" if fx.verified else "review before applying"
            out += [
                f"**Suggested change** ({fx.source}, {badge}):",
                "",
                "```diff",
                fx.diff,
                "```",
                "",
            ]
        if f.test_recommendation:
            out += [f"**Test:** {f.test_recommendation}", ""]

    out += [
        "## Method",
        "",
        "- Confidence is a ranking signal, not a probability that the finding is correct.",
        f"- Findings rejected by validation: {result.rejected_findings}"
        + (
            f" (LLM rejection rate {s.llm_rejection_rate:.1%})"
            if s.llm_rejection_rate is not None
            else ""
        ),
        f"- Prompt versions: {meta.prompt_versions or 'n/a'}",
        f"- Started {meta.started_at:%Y-%m-%d %H:%M:%S} UTC",
        "",
    ]
    if result.errors:
        out += ["## Pipeline warnings", "", *[f"- {_md_escape(e)}" for e in result.errors[:50]], ""]
    return "\n".join(out)


def to_pdf(result: ReviewResult, path: Path, title: str | None = None) -> Path:
    """Render a PDF with reportlab (the `reports` extra)."""
    title = title or ("Change Review Report" if result.change else "Code Review Report")
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            Preformatted,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise RuntimeError(
            "PDF export needs the reports extra: pip install -e '.[reports]'"
        ) from exc

    s: ReviewSummary = summarize(result)
    styles = getSampleStyleSheet()
    code_style = styles["Code"]
    code_style.fontSize = 7.5
    code_style.leading = 9
    sev_colors = {
        "critical": colors.HexColor("#8b0000"),
        "high": colors.HexColor("#c0392b"),
        "medium": colors.HexColor("#d68910"),
        "low": colors.HexColor("#2e86c1"),
        "info": colors.HexColor("#7f8c8d"),
    }

    story: list[object] = [
        Paragraph(escape(title), styles["Title"]),
        Paragraph(
            escape(
                f"{s.files_analyzed} files, {s.lines_analyzed} lines analyzed - {s.total_findings} "
                "findings"
            ),
            styles["Normal"],
        ),
        Spacer(1, 0.4 * cm),
    ]
    table_data = [["Severity", "Count", "Area", "Count"]]
    areas = [
        ("Potential bugs", s.potential_bugs),
        ("Security", s.security_issues),
        ("Error handling", s.error_handling_issues),
        ("Maintainability", s.maintainability_issues),
        ("Testing gaps", s.testing_gaps),
    ]
    for i, sev in enumerate(_SEV_ORDER):
        area = areas[i] if i < len(areas) else ("", "")
        table_data.append([sev, str(s.by_severity.get(sev, 0)), area[0], str(area[1])])
    table = Table(table_data, hAlign="LEFT", colWidths=[3 * cm, 2 * cm, 4 * cm, 2 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story += [table, Spacer(1, 0.5 * cm)]
    if result.change is not None:
        ch, sm = result.change, result.change.summary
        story.append(Paragraph("Change summary", styles["Heading2"]))
        story.append(
            Paragraph(
                escape(
                    f"{sm.base} -> {sm.head}: {sm.files_changed} file(s), "
                    f"+{sm.lines_added} / -{sm.lines_deleted} lines."
                ),
                styles["Normal"],
            )
        )
        if sm.narrative:
            story.append(Paragraph(escape(sm.narrative), styles["Normal"]))
        if sm.impacted_files:
            story.append(
                Paragraph(
                    "<b>Unchanged files that call changed code:</b> "
                    + escape(", ".join(sm.impacted_files)),
                    styles["Normal"],
                )
            )
        story.append(Paragraph("Review these hunks first", styles["Heading3"]))
        for h in ch.hunks[:MAX_HUNKS_IN_REPORT]:
            story.append(
                Paragraph(
                    f"<b>{h.level.upper()} ({h.score:.0f}/100)</b> "
                    + escape(f"{h.file}:{h.start_line}-{h.end_line} - {'; '.join(h.reasons)}"),
                    styles["Normal"],
                )
            )
            story.append(Preformatted(h.patch[:2500], code_style))
        story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Findings", styles["Heading2"]))

    for f in result.findings:
        color = sev_colors[f.severity.value].hexval()[2:]
        loc = f"{f.file}:{f.start_line}" + (f"-{f.end_line}" if f.end_line != f.start_line else "")
        story.append(
            Paragraph(
                f'<font color="#{color}"><b>{escape(f.id)} [{f.severity.value.upper()}]</b></font> '
                f"<b>{escape(f.title)}</b>",
                styles["Heading4"],
            )
        )
        meta = f"{loc} | {f.category.value}" + (f" | {f.cwe}" if f.cwe else "")
        meta += (
            f" | sources: {', '.join(x.value for x in f.sources)} | confidence {f.confidence:.2f}"
        )
        story.append(Paragraph(escape(meta), styles["Italic"]))
        story.append(Paragraph(escape(f.description).replace("\n", "<br/>"), styles["Normal"]))
        if f.evidence:
            story.append(Preformatted("\n".join(f.evidence[:3])[:1500], code_style))
        if f.related:
            story.append(
                Paragraph("<b>Related:</b> " + escape("; ".join(f.related)), styles["Normal"])
            )
        if f.recommendation:
            story.append(Paragraph("<b>Fix:</b> " + escape(f.recommendation), styles["Normal"]))
        if f.suggested_fix:
            fx = f.suggested_fix
            badge = "verified" if fx.verified else "review before applying"
            story.append(
                Paragraph(
                    f"<b>Suggested change</b> ({escape(fx.source)}, {badge})", styles["Normal"]
                )
            )
            story.append(Preformatted(fx.diff[:2500], code_style))
        if f.test_recommendation:
            story.append(
                Paragraph("<b>Test:</b> " + escape(f.test_recommendation), styles["Normal"])
            )
        story.append(Spacer(1, 0.25 * cm))

    story += [
        Paragraph("Method", styles["Heading2"]),
        Paragraph(
            "Confidence is a ranking signal, not a probability that a finding is correct.",
            styles["Normal"],
        ),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, title=title, leftMargin=1.8 * cm, rightMargin=1.8 * cm
    )
    doc.build(story)
    return path


def write_reports(
    result: ReviewResult, out_dir: Path, formats: tuple[str, ...] = ("json", "md", "pdf")
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    if "json" in formats:
        p = out_dir / "review.json"
        p.write_text(to_json(result), encoding="utf-8")
        written["json"] = p
    if "md" in formats:
        p = out_dir / "review.md"
        p.write_text(to_markdown(result), encoding="utf-8")
        written["md"] = p
    if "sarif" in formats:
        p = out_dir / "review.sarif"
        p.write_text(json.dumps(to_sarif(result), indent=2), encoding="utf-8")
        written["sarif"] = p
    if "pdf" in formats:
        written["pdf"] = to_pdf(result, out_dir / "review.pdf")
    return written


def write_reports_timed(
    result: ReviewResult, out_dir: Path, formats: tuple[str, ...] = ("json", "md", "pdf")
) -> dict[str, Path]:
    """`write_reports`, then add the report-generation time to `result.stats["timing"]`.

    A report cannot contain the time taken to write itself, so the files show the review's
    timing; the updated breakdown (total including reports) lives on `result` (result.json,
    dashboard, CLI output, timing benchmark).
    """
    start = time.perf_counter()
    written = write_reports(result, out_dir, formats)
    elapsed = time.perf_counter() - start
    timing = result.stats.get("timing")
    if isinstance(timing, dict):
        result.stats["timing"] = (
            TimingBreakdown.model_validate(timing).with_report(elapsed).model_dump()
        )
    review_id = str(result.stats.get("review_id") or out_dir.name)
    name = str(result.stats.get("source_name") or out_dir.name)
    record = from_result(result, review_id, name)
    (out_dir / "performance.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return written

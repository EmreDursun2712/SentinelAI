"""Render an incident-report markdown string to a PDF (reportlab, pure-Python).

The reporting agent already produces a clean markdown document; rather than keep a
second templating path, this walks that markdown and emits matching PDF
flowables. It understands the subset the report renderer actually uses — ``#/##/###``
headings, ``**bold**`` / ``_italic_`` / `` `code` `` inline, ``-`` bullets, ``>``
block quotes, ``---`` rules, and pipe tables — and degrades gracefully on
anything else (rendered as a plain paragraph). No system libraries are required
(unlike weasyprint), so it runs in the slim backend image as-is.
"""

from __future__ import annotations

import io
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_SLATE = colors.HexColor("#0f172a")
_ACCENT = colors.HexColor("#0e7490")
_BORDER = colors.HexColor("#cbd5e1")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=base["BodyText"], fontSize=9.5, leading=13, spaceAfter=4, alignment=TA_LEFT
    )
    return {
        "title": ParagraphStyle(
            "DocTitle",
            parent=base["Title"],
            fontSize=18,
            leading=22,
            textColor=_SLATE,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontSize=13,
            leading=16,
            textColor=_ACCENT,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontSize=11,
            leading=14,
            textColor=_SLATE,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "body": body,
        "quote": ParagraphStyle(
            "Quote",
            parent=body,
            leftIndent=10,
            textColor=colors.HexColor("#475569"),
            fontName="Helvetica-Oblique",
            borderPadding=(0, 0, 0, 6),
        ),
        "cell": ParagraphStyle("Cell", parent=body, fontSize=8.5, leading=11, spaceAfter=0),
        "cellhead": ParagraphStyle(
            "CellHead",
            parent=body,
            fontSize=8.5,
            leading=11,
            spaceAfter=0,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
    }


def _inline(text: str) -> str:
    """Markdown inline → reportlab mini-HTML markup (XML-escaped first)."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8">\1</font>', text)
    # Italic only when underscores are word-boundary bounded, so feature names
    # like ``flow_duration`` are never mangled.
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)
    return text


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def _split_row(line: str) -> list[str]:
    # Drop the leading/trailing pipe, split on unescaped pipes, unescape "\|".
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", c) for c in cells) if cells else False


def render_report_pdf(markdown: str, title: str = "Incident Report") -> bytes:
    """Render ``markdown`` to PDF bytes. Never raises on odd input."""
    styles = _styles()
    story: list = []
    lines = markdown.splitlines()
    i = 0
    n = len(lines)
    seen_title = False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            story.append(Spacer(1, 4))
            i += 1
            continue

        # Tables — collect consecutive pipe rows.
        if _is_table_row(line):
            rows: list[list[str]] = []
            while i < n and _is_table_row(lines[i]):
                rows.append(_split_row(lines[i]))
                i += 1
            story.append(_build_table(rows, styles))
            continue

        # Horizontal rule.
        if re.fullmatch(r"[-*_]{3,}", stripped):
            story.append(
                HRFlowable(width="100%", thickness=0.6, color=_BORDER, spaceBefore=4, spaceAfter=6)
            )
            i += 1
            continue

        # Headings.
        if stripped.startswith("### "):
            story.append(Paragraph(_inline(stripped[4:]), styles["h3"]))
        elif stripped.startswith("## "):
            story.append(Paragraph(_inline(stripped[3:]), styles["h2"]))
        elif stripped.startswith("# "):
            style = styles["title"] if not seen_title else styles["h2"]
            seen_title = True
            story.append(Paragraph(_inline(stripped[2:]), style))
        elif stripped.startswith("> "):
            story.append(Paragraph(_inline(stripped[2:]), styles["quote"]))
        elif stripped.startswith(("- ", "* ")):
            # Collect a run of bullet lines into one list.
            items: list[ListItem] = []
            while i < n and lines[i].strip().startswith(("- ", "* ")):
                items.append(
                    ListItem(
                        Paragraph(_inline(lines[i].strip()[2:]), styles["body"]), leftIndent=12
                    )
                )
                i += 1
            story.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=14))
            continue
        else:
            story.append(Paragraph(_inline(stripped), styles["body"]))
        i += 1

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=title,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    if not story:
        story.append(Paragraph("(empty report)", styles["body"]))
    doc.build(story)
    return buf.getvalue()


def _build_table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> Table:
    header = rows[0]
    body_rows = rows[1:]
    if body_rows and _is_separator_row(body_rows[0]):
        body_rows = body_rows[1:]

    ncols = max(len(r) for r in rows)
    header = header + [""] * (ncols - len(header))

    data = [[Paragraph(_inline(c), styles["cellhead"]) for c in header]]
    for r in body_rows:
        r = r + [""] * (ncols - len(r))
        data.append([Paragraph(_inline(c), styles["cell"]) for c in r])

    avail = A4[0] - 36 * mm
    table = Table(data, colWidths=[avail / ncols] * ncols, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
                ("GRID", (0, 0), (-1, -1), 0.4, _BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table

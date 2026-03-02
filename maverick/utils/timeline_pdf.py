from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _safe_text(value: object, fallback: str = "N/A") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _format_date(value: object) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%b %d, %Y")
    return _safe_text(value, "TBD")


def _deadline_label(row: dict) -> str:
    raw = (row.get("description") or "").strip()
    if raw:
        return raw
    return (row.get("deadline_type") or "").replace("_", " ").title()


def _build_gantt_drawing(deadline_rows: Iterable[dict]) -> Drawing | None:
    rows = [row for row in deadline_rows if isinstance(row.get("deadline_date"), date)]
    if not rows:
        return None

    rows.sort(key=lambda item: item["deadline_date"])
    start_date = rows[0]["deadline_date"]
    end_date = rows[-1]["deadline_date"]
    span_days = max((end_date - start_date).days, 1)

    width = 520
    left_label_x = 6
    axis_x0 = 185
    axis_x1 = width - 20
    axis_width = axis_x1 - axis_x0
    row_height = 22
    top_padding = 38
    height = top_padding + (row_height * len(rows)) + 16
    drawing = Drawing(width, height)

    drawing.add(
        String(
            left_label_x,
            height - 16,
            f"Timeline range: {_format_date(start_date)} to {_format_date(end_date)}",
            fontSize=9,
            fillColor=colors.HexColor("#334155"),
        )
    )
    drawing.add(Line(axis_x0, 18, axis_x1, 18, strokeColor=colors.HexColor("#94a3b8"), strokeWidth=1.2))
    drawing.add(String(axis_x0 - 4, 4, _format_date(start_date), fontSize=8, fillColor=colors.HexColor("#64748b")))
    drawing.add(String(axis_x1 - 60, 4, _format_date(end_date), fontSize=8, fillColor=colors.HexColor("#64748b")))

    today = date.today()
    if start_date <= today <= end_date:
        today_offset = (today - start_date).days / span_days
        today_x = axis_x0 + (axis_width * today_offset)
        drawing.add(Line(today_x, 18, today_x, height - 20, strokeColor=colors.HexColor("#f59e0b"), strokeWidth=0.8))
        drawing.add(String(today_x + 3, height - 28, "Today", fontSize=8, fillColor=colors.HexColor("#b45309")))

    for index, row in enumerate(rows):
        row_y = height - top_padding - (index * row_height)
        deadline_date = row["deadline_date"]
        offset = (deadline_date - start_date).days / span_days
        marker_x = axis_x0 + (axis_width * offset)

        drawing.add(
            String(
                left_label_x,
                row_y - 2,
                _deadline_label(row)[:42],
                fontSize=8.5,
                fillColor=colors.HexColor("#0f172a"),
            )
        )
        drawing.add(Rect(marker_x - 2.5, row_y - 5.5, 5.5, 5.5, fillColor=colors.HexColor("#1d4ed8"), strokeColor=None))
        drawing.add(
            String(
                marker_x + 6,
                row_y - 2,
                _format_date(deadline_date),
                fontSize=8,
                fillColor=colors.HexColor("#334155"),
            )
        )
        drawing.add(Line(axis_x0, row_y - 2.5, axis_x1, row_y - 2.5, strokeColor=colors.HexColor("#e2e8f0"), strokeWidth=0.4))

    return drawing


def build_timeline_pdf(output_path: str, context: dict) -> str:
    """
    Generate a professional transaction timeline PDF.

    Args:
        output_path: Destination filepath.
        context: Timeline context payload with transaction/party/deadline details.

    Returns:
        output_path
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
        title=f"Maverick Timeline #{context.get('transaction_id')}",
    )
    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "Heading2Compact",
        parent=styles["Heading2"],
        spaceBefore=8,
        spaceAfter=6,
        textColor=colors.HexColor("#0f172a"),
    )
    body = styles["BodyText"]
    body.spaceAfter = 5

    story: list = []

    story.append(Paragraph("Maverick Transaction Timeline Packet", styles["Title"]))
    story.append(
        Paragraph(
            f"Transaction #{context.get('transaction_id')} | {_safe_text(context.get('property_address'))}",
            ParagraphStyle(
                "Subtitle",
                parent=styles["BodyText"],
                textColor=colors.HexColor("#334155"),
                fontSize=11,
                leading=14,
            ),
        )
    )
    story.append(Spacer(1, 8))

    summary_table = Table(
        [
            ["Effective Date", _format_date(context.get("effective_date"))],
            ["Closing Date", _format_date(context.get("closing_date"))],
            ["Transaction Pace", _safe_text(context.get("service_level"), "Standard")],
            ["Packet Updated", _format_date(context.get("generated_at"))],
        ],
        colWidths=[150, 360],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#cbd5e1")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 8))

    story.append(Paragraph("12-Deadline Timeline", heading))
    deadline_rows = context.get("deadlines") or []
    gantt = _build_gantt_drawing(deadline_rows)
    if gantt:
        story.append(gantt)
        story.append(Spacer(1, 6))

    deadline_table_rows = [["Deadline", "Date", "Status"]] + [
        [
            _deadline_label(item),
            _format_date(item.get("deadline_date")),
            "Complete" if item.get("completed") else "Pending",
        ]
        for item in deadline_rows
    ]
    deadline_table = Table(deadline_table_rows, colWidths=[245, 120, 145], repeatRows=1)
    deadline_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(deadline_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("What to Expect Each Week", heading))
    for bullet in context.get("weekly_expectations") or []:
        story.append(Paragraph(f"- {bullet}", body))

    story.append(Paragraph("Payment + Document Milestones", heading))
    for bullet in context.get("payment_document_points") or []:
        story.append(Paragraph(f"- {bullet}", body))

    story.append(Paragraph("Inspection / Appraisal Windows", heading))
    for bullet in context.get("inspection_appraisal_points") or []:
        story.append(Paragraph(f"- {bullet}", body))

    story.append(Paragraph("Moving Checklist", heading))
    for bullet in context.get("moving_checklist") or []:
        story.append(Paragraph(f"- {bullet}", body))

    story.append(Spacer(1, 8))
    story.append(Paragraph("Key Contacts", heading))
    contacts = context.get("contacts") or {}
    contact_table = Table(
        [
            ["Buyer", _safe_text(contacts.get("buyer"))],
            ["Seller", _safe_text(contacts.get("seller"))],
            ["Agent", _safe_text(contacts.get("agent"))],
            ["Lender", _safe_text(contacts.get("lender"))],
            ["Title", _safe_text(contacts.get("title"))],
            ["Margaret", _safe_text(contacts.get("margaret"))],
        ],
        colWidths=[90, 420],
    )
    contact_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.8),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(contact_table)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"Secure document upload portal: {_safe_text(context.get('upload_portal_link'), 'Available in client portal message')}",
            body,
        )
    )
    story.append(
        Paragraph(
            "Questions? Reply to your Maverick email thread or contact Margaret directly.",
            ParagraphStyle(
                "FooterNote",
                parent=styles["BodyText"],
                textColor=colors.HexColor("#475569"),
                fontSize=9,
            ),
        )
    )

    doc.build(story)
    return output_path

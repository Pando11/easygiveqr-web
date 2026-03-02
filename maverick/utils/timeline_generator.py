import io
import os
from datetime import date, datetime, timedelta

import boto3
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from utils.db import execute_query, get_transaction_deadlines


def _get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION"),
    )


def _safe_text(value, fallback="N/A"):
    text = str(value or "").strip()
    return text if text else fallback


def _format_date(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%B %d, %Y")
    return _safe_text(value, "TBD")


def get_transaction_by_id(transaction_id):
    """Fetch transaction values required by timeline PDF generation."""
    rows = execute_query(
        """
        SELECT
            id,
            property_address,
            effective_date,
            closing_date,
            option_fee_due_date,
            earnest_due_date,
            buyer_name,
            seller_name,
            agent_name,
            agent_phone,
            rush_service
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def generate_weekly_expectations(transaction, deadlines):
    """
    Create week-by-week breakdown of what buyer/seller should expect.
    """
    effective_date = transaction.get("effective_date")
    closing_date = transaction.get("closing_date")
    if not effective_date or not closing_date or closing_date < effective_date:
        return [
            {
                "number": 1,
                "title": "Contract Execution & Initial Steps",
                "description": (
                    "- Contract becomes effective\n"
                    "- Earnest and option payments are submitted\n"
                    "- Inspection scheduling begins\n"
                    "- Maverick starts milestone coordination"
                ),
            }
        ]

    total_days = max((closing_date - effective_date).days, 1)
    total_weeks = max(1, min(8, (total_days // 7) + (1 if total_days % 7 else 0)))
    week_titles = [
        "Contract Execution & Initial Steps",
        "Inspection & Due Diligence",
        "Financing, Title & Survey Progress",
        "Pre-Closing Preparation",
        "Closing Week Readiness",
        "Extension / Contingency Management",
        "Final Coordination",
        "Close & Archive",
    ]

    weeks = []
    sorted_deadlines = sorted(
        [row for row in deadlines if row.get("deadline_date")],
        key=lambda item: item["deadline_date"],
    )
    for week_idx in range(total_weeks):
        week_number = week_idx + 1
        week_start = effective_date + timedelta(days=week_idx * 7)
        week_end = min(closing_date, week_start + timedelta(days=6))
        title = week_titles[min(week_idx, len(week_titles) - 1)]

        week_deadlines = []
        for row in sorted_deadlines:
            deadline_date = row.get("deadline_date")
            if week_start <= deadline_date <= week_end:
                label = (row.get("description") or "").strip() or (row.get("deadline_type") or "").replace("_", " ").title()
                week_deadlines.append(f"- {label}: {deadline_date.strftime('%b %d')}")

        base_lines = [
            f"- Week window: {week_start.strftime('%b %d')} to {week_end.strftime('%b %d')}",
            "- Maverick monitors progress and sends proactive reminders as needed.",
        ]
        if week_number == 1:
            base_lines.extend(
                [
                    "- Contract is activated and all parties are synced on dates.",
                    "- Earnest money and option-period tasks should be completed quickly.",
                ]
            )
        elif week_number == total_weeks:
            base_lines.extend(
                [
                    "- Final confirmations are completed before closing.",
                    "- Wire, title, and final logistics are verified.",
                ]
            )
        else:
            base_lines.extend(
                [
                    "- Key inspections, lender updates, and title work continue.",
                    "- Any timeline drift is flagged with clear next-step recommendations.",
                ]
            )

        if week_deadlines:
            base_lines.append("- Milestones this week:")
            base_lines.extend(week_deadlines)

        weeks.append(
            {
                "number": week_number,
                "title": title,
                "description": "\n".join(base_lines),
            }
        )

    return weeks


def _build_timeline_pdf_bytes(transaction, deadlines):
    """
    Build timeline PDF bytes using ReportLab.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
        title=f"Transaction Timeline #{transaction['id']}",
    )
    elements = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=colors.HexColor("#1e3a8a"),
        spaceAfter=24,
    )
    normal_style = ParagraphStyle(
        "NormalWithBreaks",
        parent=styles["BodyText"],
        leading=14,
        spaceAfter=10,
    )

    elements.append(Paragraph("Transaction Timeline", title_style))
    elements.append(Paragraph(_safe_text(transaction.get("property_address")), styles["Heading2"]))
    elements.append(Spacer(1, 0.25 * inch))

    summary_data = [
        ["Transaction #", str(transaction["id"])],
        ["Effective Date", _format_date(transaction.get("effective_date"))],
        ["Closing Date", _format_date(transaction.get("closing_date"))],
        ["Buyer", _safe_text(transaction.get("buyer_name"))],
        ["Seller", _safe_text(transaction.get("seller_name"))],
        ["Agent", _safe_text(transaction.get("agent_name"))],
        ["Your Coordinator", f"Margaret - {_safe_text(os.getenv('MARGARET_PHONE'), 'Not configured')}"],
    ]
    summary_table = Table(summary_data, colWidths=[2 * inch, 4.8 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f9ff")),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1e3a8a")),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94a3b8")),
            ]
        )
    )
    elements.append(summary_table)
    elements.append(Spacer(1, 0.35 * inch))

    elements.append(Paragraph("Important Deadlines", styles["Heading2"]))
    elements.append(Spacer(1, 0.15 * inch))

    deadline_data = [["Date", "Milestone", "Days From Now", "Status"]]
    status_style_commands = []
    today = date.today()
    ordered_deadlines = sorted(deadlines, key=lambda row: row.get("deadline_date") or date.max)
    for row_index, deadline in enumerate(ordered_deadlines, start=1):
        deadline_date = deadline.get("deadline_date")
        if not deadline_date:
            continue
        days_from_now = (deadline_date - today).days
        if days_from_now > 0:
            days_text = f"{days_from_now} days"
        elif days_from_now == 0:
            days_text = "TODAY"
        else:
            days_text = "PAST"

        is_complete = bool(deadline.get("completed"))
        status_value = "DONE" if is_complete else "OPEN"
        status_color = colors.HexColor("#166534") if is_complete else (colors.HexColor("#d97706") if days_from_now >= 0 else colors.HexColor("#b91c1c"))

        milestone = (deadline.get("description") or "").strip() or (deadline.get("deadline_type") or "").replace("_", " ").title()
        deadline_data.append(
            [
                deadline_date.strftime("%b %d"),
                milestone,
                days_text,
                status_value,
            ]
        )
        status_style_commands.append(("TEXTCOLOR", (3, row_index), (3, row_index), status_color))
        status_style_commands.append(("FONTNAME", (3, row_index), (3, row_index), "Helvetica-Bold"))

    deadline_table = Table(deadline_data, colWidths=[1.0 * inch, 3.6 * inch, 1.2 * inch, 0.8 * inch], repeatRows=1)
    deadline_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 11),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#94a3b8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]
    deadline_table.setStyle(TableStyle(deadline_style + status_style_commands))
    elements.append(deadline_table)
    elements.append(PageBreak())

    elements.append(Paragraph("What to Expect Each Week", styles["Heading2"]))
    elements.append(Spacer(1, 0.15 * inch))
    for week in generate_weekly_expectations(transaction, ordered_deadlines):
        elements.append(Paragraph(f"Week {week['number']}: {week['title']}", styles["Heading3"]))
        text = (week.get("description") or "").replace("\n", "<br/>")
        elements.append(Paragraph(text, normal_style))
        elements.append(Spacer(1, 0.08 * inch))

    doc.build(elements)
    return buffer.getvalue()


def generate_transaction_timeline_pdf_bytes(transaction_id):
    """
    Generate timeline PDF bytes and a filename for one transaction.
    """
    transaction = get_transaction_by_id(transaction_id)
    if not transaction:
        raise ValueError("Transaction not found")
    deadlines = get_transaction_deadlines(transaction_id)
    pdf_bytes = _build_timeline_pdf_bytes(transaction, deadlines)
    filename = f"timeline_{transaction['id']}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return {
        "transaction": transaction,
        "deadlines": deadlines,
        "pdf_bytes": pdf_bytes,
        "filename": filename,
    }


def upload_transaction_timeline_pdf(transaction_id, pdf_bytes, filename):
    """Upload timeline PDF bytes to S3 and return its object key."""
    bucket = (os.getenv("AWS_S3_BUCKET_DOCUMENTS") or "").strip()
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET_DOCUMENTS is not configured")
    safe_filename = (filename or f"timeline_{transaction_id}_{datetime.now().strftime('%Y%m%d')}.pdf").strip()
    s3_key = f"timelines/{transaction_id}/{safe_filename}"
    _get_s3_client().upload_fileobj(
        io.BytesIO(pdf_bytes),
        bucket,
        s3_key,
        ExtraArgs={"ContentType": "application/pdf"},
    )
    return s3_key


def generate_transaction_timeline_pdf(transaction_id):
    """
    Generate beautiful PDF timeline for transaction.

    Returns:
        S3 key where PDF is stored.
    """
    payload = generate_transaction_timeline_pdf_bytes(transaction_id)
    return upload_transaction_timeline_pdf(
        transaction_id=transaction_id,
        pdf_bytes=payload["pdf_bytes"],
        filename=payload["filename"],
    )

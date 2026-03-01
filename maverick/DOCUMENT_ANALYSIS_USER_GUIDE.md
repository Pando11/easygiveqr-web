# Document Analysis User Guide (HOA + Inspection)

This guide explains Maverick's automated HOA and inspection report analysis workflow for TC operations.

## What gets analyzed

Supported document categories:

- HOA documents (`hoa`, `hoa_documents`, `hoa_docs`)
- Inspection reports (`inspection`, `inspection_report`)

Only PDF files are currently analyzed automatically.

## Analysis engine

Maverick runs a triple-scan text pipeline:

1. OCR (`pdf2image` + `pytesseract`)
2. Direct PDF text (`PyPDF2`)
3. Layout-preserved extraction (`pdfplumber`)

Findings are flagged only when at least **2 of 3 methods agree**.

Confidence labels:
- **High** = `3/3`
- **Medium** = `2/3`
- **Low** = `1/3` (not auto-flagged)

## Smart notifications

Immediate SMS alerts to Margaret are sent when:

- HOA special assessment > $3,000
- Inspection safety issues are detected
- Estimated repair cost > $10,000

All other alerts are converted to due-today checklist tasks.

## Margaret workflow

1. Open transaction -> Documents section.
2. Check **Document Analysis** summary.
3. Click **View Full Analysis Dashboard**.
4. Review generated findings and action items.
5. Add notes and mark records as reviewed.
6. Override auto-created tasks when necessary with **Override Task (Mark N/A)**.

## Audit trail

Maverick logs:

- analysis runs
- generated action items
- SMS/task actions
- review actions
- task overrides

These are recorded in `document_analysis_results`, `tasks`, and `communications`.

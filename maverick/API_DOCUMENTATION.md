# Maverick API Documentation

This document covers API-style routes used by mobile clients and the tokenized client portal.

## Authentication

### Mobile JWT

1. Obtain token:
   - `POST /api/mobile/login`
   - Body:
     ```json
     {
       "username": "margaret",
       "password": "your-tc-password"
     }
     ```
2. Use token:
   - Header: `Authorization: Bearer <access_token>`

## Mobile Endpoints

### Dashboard
- `GET /api/mobile/dashboard`

### Daily checklist
- `GET /api/mobile/daily-checklist`

### Task completion
- `POST /api/mobile/task/<task_id>/complete`
- Body:
  ```json
  { "completed": true }
  ```

### Call completion
- `POST /api/mobile/call/<deadline_id>/complete`
- Body:
  ```json
  { "made": true }
  ```

### Documents
- `GET /api/mobile/transaction/<transaction_id>/documents`

### Communications
- `GET /api/mobile/transaction/<transaction_id>/communications`
- `POST /api/mobile/transaction/<transaction_id>/communications`
- Body:
  ```json
  {
    "communication_type": "phone_call",
    "contact_party": "agent",
    "contact_name": "Optional Name",
    "summary": "Called to confirm timeline",
    "outcome": "Waiting on lender update",
    "follow_up_date": "2026-02-20"
  }
  ```

## Client Portal Endpoints

Client portal uses a unique token URL and does not require login credentials.

### Overview
- `GET /client/<access_token>`

### Timeline
- `GET /client/<access_token>/timeline`

### Documents + upload view
- `GET /client/<access_token>/documents`

### Upload signed document
- `POST /client/<access_token>/upload`
- Form fields:
  - `document_type`
  - `document_file` (pdf/jpg/jpeg/png)

## TC Utility Route

### Generate or re-send client portal links
- `POST /tc/transaction/<transaction_id>/generate-client-portal`

### Document analysis dashboard
- `GET /tc/transaction/<transaction_id>/document-analysis`

### Mark analysis reviewed / add notes
- `POST /tc/transaction/<transaction_id>/document-analysis/<analysis_id>/review`

### Override auto-created analysis task
- `POST /tc/transaction/<transaction_id>/document-analysis/override-task`
- Form body:
  - `task_id`

## TC Extraction Verification Routes

### Save verified extraction values
- `POST /tc/transaction/<transaction_id>/verify-extraction`
- Form fields (required):
  - `verified_effective_date` (YYYY-MM-DD)
  - `verified_closing_date` (YYYY-MM-DD)
  - `verified_buyer_name`
  - `verified_seller_name`
  - `verified_property_address`

### Legacy alias (still accepted)
- `POST /tc/transaction/<transaction_id>/confirm-extraction`

## Extraction Engine Notes

Contract uploads trigger asynchronous triple-scan extraction:

1. OCR: `pdf2image` + `pytesseract`
2. Direct text: `PyPDF2`
3. Layout-aware text: `pdfplumber`

The system writes field-level confidence rows to `contract_extractions` and requires manual verification before approval.

## Automated HOA / Inspection Analysis

When these document types are uploaded:
- HOA: `hoa`, `hoa_documents`, `hoa_docs`
- Inspection: `inspection`, `inspection_report`

Maverick:
1. Downloads the PDF from S3
2. Runs triple-scan extraction (OCR + PyPDF2 + pdfplumber)
3. Flags findings only when at least `2/3` methods agree
4. Stores analysis in `document_analysis_results`
5. Executes action items (alerts/tasks) with smart thresholds

# Triple-Scan Extraction Verification Guide

This guide explains how Maverick extracts contract fields and how Margaret verifies them before activation.

## Extraction methods

Maverick runs three independent extraction methods:

1. **Method 1 (OCR):** `pdf2image` + `pytesseract`
2. **Method 2 (Direct text):** `PyPDF2`
3. **Method 3 (Layout text):** `pdfplumber`

Each method attempts to extract:
- Effective date
- Closing date
- Buyer name(s)
- Seller name(s)
- Property address

## Confidence model

For each field, Maverick compares method outputs:

- `3/3` agreement -> **High confidence**
- `2/3`, `1/3`, or `0/3` -> **Low confidence**

Field-level values are stored in `contract_extractions`.

## Margaret verification flow

1. Open transaction in review mode.
2. In **AI Contract Extraction (Triple-Scan Verification)**:
   - Use **Accept High-Confidence Values** for quick fill.
   - Review low-confidence method outputs.
   - Select the best extracted option or type manually.
3. Click **Save Verified Extraction**.
4. Confirm all required fields are verified.
5. Complete approval fields and activate transaction.

## Required verification fields

- Effective Date
- Closing Date
- Buyer Name(s)
- Seller Name(s)
- Property Address

Approval is blocked until all required fields are verified.

## Troubleshooting

### No extracted values
- Confirm contract PDF is readable and not image-corrupted.
- Re-upload the contract if needed.
- Enter values manually and save verification.

### Date parse errors
- Use `YYYY-MM-DD` in verification fields.
- Confirm closing date is not before effective date.

### Persistent low confidence
- Trust the contract PDF over extracted text.
- Manually enter the correct value and save verification.

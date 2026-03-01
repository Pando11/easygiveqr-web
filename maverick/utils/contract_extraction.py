import re
from datetime import datetime
from typing import Dict

from pdf2image import convert_from_path
from PyPDF2 import PdfReader
import pdfplumber
import pytesseract

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - optional dependency path
    Anthropic = None


DATE_CAPTURE_PATTERN = (
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})"
)
EFFECTIVE_DATE_PATTERNS = (
    rf"effective\s+date\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
    rf"date\s+of\s+effective\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
)
CLOSING_DATE_PATTERNS = (
    rf"closing\s+date\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
    rf"close\s+of\s+escrow\s*[:\-]?\s*{DATE_CAPTURE_PATTERN}",
)
BUYER_PATTERNS = (
    r"buyer(?:\(s\))?\s*[:\-]\s*([^\n\r]{2,180})",
    r"purchaser(?:\(s\))?\s*[:\-]\s*([^\n\r]{2,180})",
)
SELLER_PATTERNS = (
    r"seller(?:\(s\))?\s*[:\-]\s*([^\n\r]{2,180})",
    r"owner(?:\(s\))?\s*[:\-]\s*([^\n\r]{2,180})",
)
PROPERTY_ADDRESS_PATTERNS = (
    r"property\s+address\s*[:\-]\s*([^\n\r]{6,240})",
    r"address\s+of\s+property\s*[:\-]\s*([^\n\r]{6,240})",
)
DATE_PARSE_FORMATS = (
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%m/%d/%y",
    "%m-%d-%y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
)

SUPPORTED_FIELDS = (
    "effective_date",
    "closing_date",
    "buyer_name",
    "seller_name",
    "property_address",
)


def _empty_extraction_payload() -> Dict[str, str]:
    return {
        "effective_date": "",
        "closing_date": "",
        "buyer_name": "",
        "seller_name": "",
        "property_address": "",
        "_raw_text": "",
        "_error": "",
    }


def _cleanup_name_candidate(raw_value: str) -> str:
    value = (raw_value or "").strip(" ,.;:-")
    value = re.sub(r"\s{2,}", " ", value)
    value = re.split(r"\s+(?:phone|email|address|date)\s*[:\-]", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return value[:180].strip(" ,.;:-")


def _cleanup_address_candidate(raw_value: str) -> str:
    value = (raw_value or "").strip(" ,.;:-")
    value = re.sub(r"\s{2,}", " ", value)
    value = re.split(r"\s+(?:county|lot|block)\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    return value[:240].strip(" ,.;:-")


def _parse_contract_date(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    value = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    for fmt in DATE_PARSE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _extract_pattern_value(text: str, patterns, cleanup_func=None) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = (match.group(1) or "").strip()
        if cleanup_func:
            value = cleanup_func(value)
        if value:
            return value
    return ""


def _parse_contract_text(text: str) -> Dict[str, str]:
    payload = _empty_extraction_payload()
    payload["_raw_text"] = text

    lower_text = text.lower()
    effective_date = ""
    for pattern in EFFECTIVE_DATE_PATTERNS:
        match = re.search(pattern, lower_text, flags=re.IGNORECASE)
        if not match:
            continue
        effective_date = _parse_contract_date(match.group(1))
        if effective_date:
            break

    closing_date = ""
    for pattern in CLOSING_DATE_PATTERNS:
        match = re.search(pattern, lower_text, flags=re.IGNORECASE)
        if not match:
            continue
        closing_date = _parse_contract_date(match.group(1))
        if closing_date:
            break

    payload["effective_date"] = effective_date
    payload["closing_date"] = closing_date
    payload["buyer_name"] = _extract_pattern_value(text, BUYER_PATTERNS, cleanup_func=_cleanup_name_candidate)
    payload["seller_name"] = _extract_pattern_value(text, SELLER_PATTERNS, cleanup_func=_cleanup_name_candidate)
    payload["property_address"] = _extract_pattern_value(
        text,
        PROPERTY_ADDRESS_PATTERNS,
        cleanup_func=_cleanup_address_candidate,
    )
    return payload


def extract_via_ocr(pdf_path: str) -> Dict[str, str]:
    """Method 1: OCR using Tesseract."""
    payload = _empty_extraction_payload()
    try:
        images = convert_from_path(pdf_path, first_page=1, last_page=3)
        page_text_chunks = []
        for page_index, image in enumerate(images, start=1):
            text = pytesseract.image_to_string(image) or ""
            page_text_chunks.append(f"\n--- PAGE {page_index} ---\n{text}")
        parsed = _parse_contract_text("\n".join(page_text_chunks).strip())
        payload.update(parsed)
    except Exception as exc:
        payload["_error"] = str(exc)
    return payload


def extract_via_pypdf(pdf_path: str) -> Dict[str, str]:
    """Method 2: Direct text extraction using PyPDF2."""
    payload = _empty_extraction_payload()
    try:
        reader = PdfReader(pdf_path)
        page_text_chunks = []
        for page in reader.pages[:3]:
            page_text_chunks.append(page.extract_text() or "")
        parsed = _parse_contract_text("\n".join(page_text_chunks).strip())
        payload.update(parsed)
    except Exception as exc:
        payload["_error"] = str(exc)
    return payload


def extract_via_pdfplumber(pdf_path: str) -> Dict[str, str]:
    """Method 3: Text extraction using pdfplumber."""
    payload = _empty_extraction_payload()
    try:
        page_text_chunks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:3]:
                page_text_chunks.append(page.extract_text(layout=True) or "")
        parsed = _parse_contract_text("\n".join(page_text_chunks).strip())
        payload.update(parsed)
    except Exception as exc:
        payload["_error"] = str(exc)
    return payload


def compare_extractions(method1_data, method2_data, method3_data):
    """Compare results from all 3 methods."""
    compared: Dict[str, Dict[str, str]] = {}
    for field_name in SUPPORTED_FIELDS:
        values = [
            (method1_data or {}).get(field_name) or "",
            (method2_data or {}).get(field_name) or "",
            (method3_data or {}).get(field_name) or "",
        ]
        cleaned = [value.strip() if isinstance(value, str) else str(value or "").strip() for value in values]
        non_empty = [value for value in cleaned if value]

        if not non_empty:
            best_value = ""
            agreement_count = 0
        else:
            value_counts = {}
            first_seen_position = {}
            for index, value in enumerate(cleaned):
                if not value:
                    continue
                value_counts[value] = value_counts.get(value, 0) + 1
                if value not in first_seen_position:
                    first_seen_position[value] = index
            ranked = sorted(
                value_counts.items(),
                key=lambda item: (-item[1], first_seen_position[item[0]]),
            )
            best_value, agreement_count = ranked[0]

        compared[field_name] = {
            "value": best_value,
            "confidence": "high" if agreement_count == 3 else "low",
            "agreement": f"{agreement_count}/3",
            "method1_value": cleaned[0],
            "method2_value": cleaned[1],
            "method3_value": cleaned[2],
        }
    return compared


def extract_via_anthropic(raw_text: str, api_key: str):
    """Optional 4th verification using Claude if API key is configured."""
    if not api_key or Anthropic is None:
        return {}
    prompt = (
        "Extract these fields from this real estate contract text and return JSON only: "
        "effective_date (YYYY-MM-DD), closing_date (YYYY-MM-DD), buyer_name, seller_name, property_address.\n\n"
        f"TEXT:\n{raw_text[:12000]}"
    )
    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=500,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text_response = ""
        for content_item in getattr(response, "content", []) or []:
            if getattr(content_item, "type", "") == "text":
                text_response += content_item.text
        return {"raw_response": text_response.strip()}
    except Exception:
        return {}

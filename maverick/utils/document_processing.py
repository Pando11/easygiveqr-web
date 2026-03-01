from __future__ import annotations

import io
import json
import os
import re
from datetime import date
from typing import Any

from PyPDF2 import PdfReader

try:
    import pytesseract
except Exception:  # pragma: no cover - optional at runtime
    pytesseract = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional at runtime
    Image = None

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - optional at runtime
    Anthropic = None

from utils.db import execute_query
from utils.s3 import upload_document


KNOWN_DOCUMENT_TYPES = {
    "contract",
    "earnest_receipt",
    "option_receipt",
    "seller_disclosure",
    "survey",
    "hoa_docs",
    "title_commitment",
    "inspection_report",
    "appraisal",
    "loan_approval",
    "insurance_binder",
    "settlement_statement",
    "signed_amendment",
    "signed_disclosure",
    "signed_addendum",
    "timeline_packet",
    "other",
    "unknown",
}

DOCUMENT_TYPE_SYNONYMS = {
    "earnest_money_receipt": "earnest_receipt",
    "earnest receipt": "earnest_receipt",
    "earnest": "earnest_receipt",
    "option fee receipt": "option_receipt",
    "hoa": "hoa_docs",
    "hoa_documents": "hoa_docs",
    "homeowners_association_docs": "hoa_docs",
    "inspection": "inspection_report",
    "inspection report": "inspection_report",
    "appraisal_report": "appraisal",
    "title": "title_commitment",
    "title file": "title_commitment",
    "loan approval letter": "loan_approval",
    "insurance": "insurance_binder",
    "closing_disclosure": "settlement_statement",
    "cd": "settlement_statement",
    "hud": "settlement_statement",
}


def ensure_document_classification_corrections_table():
    """Persist Margaret corrections so classification can adapt over time."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS document_classification_corrections (
            id SERIAL PRIMARY KEY,
            document_id INT REFERENCES documents(id) ON DELETE SET NULL,
            transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
            original_document_type VARCHAR(100) NOT NULL,
            corrected_document_type VARCHAR(100) NOT NULL,
            first_page_signature VARCHAR(64),
            first_page_excerpt TEXT,
            correction_reason TEXT,
            corrected_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_doc_classification_corrections_doc
        ON document_classification_corrections(document_id, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_doc_classification_corrections_type_map
        ON document_classification_corrections(original_document_type, corrected_document_type, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_doc_classification_corrections_txn
        ON document_classification_corrections(transaction_id, created_at DESC)
        """
    )


def normalize_document_type(raw_value, fallback="other"):
    value = (raw_value or "").strip().lower().replace("-", "_")
    value = DOCUMENT_TYPE_SYNONYMS.get(value, value)
    if value in KNOWN_DOCUMENT_TYPES:
        return value
    return fallback


def extract_text_from_first_page(file_bytes, extension):
    """Extract first-page text from PDF/image uploads."""
    raw = file_bytes if isinstance(file_bytes, (bytes, bytearray)) else b""
    ext = (extension or "").strip().lower()
    if not raw:
        return ""

    try:
        if ext == "pdf":
            reader = PdfReader(io.BytesIO(raw))
            if not reader.pages:
                return ""
            return re.sub(r"\s+", " ", (reader.pages[0].extract_text() or "")).strip()[:12000]

        if ext in {"jpg", "jpeg", "png"} and Image and pytesseract:
            image = Image.open(io.BytesIO(raw))
            return re.sub(r"\s+", " ", (pytesseract.image_to_string(image) or "")).strip()[:12000]
    except Exception:
        return ""
    return ""


def _extract_json_from_text(raw_text):
    text = (raw_text or "").strip()
    if not text:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]

    try:
        return json.loads(candidate)
    except Exception:
        # Handle model output that uses single quotes.
        try:
            normalized = re.sub(r"'", '"', candidate)
            return json.loads(normalized)
        except Exception:
            return None


def _extract_claude_text_response(response):
    parts = []
    for item in getattr(response, "content", []) or []:
        if getattr(item, "type", "") == "text":
            parts.append(getattr(item, "text", ""))
    return "\n".join(part for part in parts if part).strip()


def _heuristic_document_type(first_page_text, suggested_type="other"):
    text = (first_page_text or "").lower()
    if "inspection report" in text or ("inspector" in text and "defect" in text):
        return {"type": "inspection_report", "confidence": 86, "key_info_extracted": {}, "source": "heuristic"}
    if "earnest" in text and ("receipt" in text or "deposit" in text):
        return {"type": "earnest_receipt", "confidence": 90, "key_info_extracted": {}, "source": "heuristic"}
    if "option fee" in text and ("receipt" in text or "paid" in text):
        return {"type": "option_receipt", "confidence": 84, "key_info_extracted": {}, "source": "heuristic"}
    if "seller" in text and "disclosure" in text:
        return {"type": "seller_disclosure", "confidence": 84, "key_info_extracted": {}, "source": "heuristic"}
    if "title commitment" in text or ("schedule b" in text and "title" in text):
        return {"type": "title_commitment", "confidence": 86, "key_info_extracted": {}, "source": "heuristic"}
    if "appraised value" in text or "uniform residential appraisal report" in text:
        return {"type": "appraisal", "confidence": 86, "key_info_extracted": {}, "source": "heuristic"}
    if "loan approval" in text or "commitment letter" in text:
        return {"type": "loan_approval", "confidence": 82, "key_info_extracted": {}, "source": "heuristic"}
    if "insurance binder" in text or "certificate of insurance" in text:
        return {"type": "insurance_binder", "confidence": 82, "key_info_extracted": {}, "source": "heuristic"}
    if "settlement statement" in text or "closing disclosure" in text or "hud-1" in text:
        return {"type": "settlement_statement", "confidence": 83, "key_info_extracted": {}, "source": "heuristic"}
    if "survey" in text and ("boundary" in text or "metes and bounds" in text):
        return {"type": "survey", "confidence": 80, "key_info_extracted": {}, "source": "heuristic"}
    if "hoa" in text or "homeowners association" in text:
        return {"type": "hoa_docs", "confidence": 78, "key_info_extracted": {}, "source": "heuristic"}

    fallback = normalize_document_type(suggested_type, fallback="other")
    confidence = 56 if fallback != "other" else 45
    return {"type": fallback, "confidence": confidence, "key_info_extracted": {}, "source": "heuristic"}


def _learned_type_override(predicted_type):
    """Use correction history to improve future type predictions."""
    ensure_document_classification_corrections_table()
    normalized_prediction = normalize_document_type(predicted_type, fallback="unknown")
    rows = execute_query(
        """
        SELECT corrected_document_type, COUNT(*) AS usage_count
        FROM document_classification_corrections
        WHERE original_document_type = %s
        GROUP BY corrected_document_type
        ORDER BY usage_count DESC, corrected_document_type ASC
        LIMIT 3
        """,
        (normalized_prediction,),
        fetch=True,
    ) or []
    if not rows:
        return None

    top = rows[0]
    top_type = normalize_document_type(top.get("corrected_document_type"), fallback="unknown")
    top_count = int(top.get("usage_count") or 0)
    total = sum(int(row.get("usage_count") or 0) for row in rows)
    if total <= 0:
        return None
    share = top_count / total
    if top_count >= 2 and share >= 0.6 and top_type != normalized_prediction:
        return {"type": top_type, "confidence_boost": 6}
    return None


def identify_document_type(first_page_text, transaction_context, suggested_type="other"):
    """
    Use Claude (when configured) + heuristics to classify document type.
    If confidence < 70, returns type='unknown' per safety rule.
    """
    context = transaction_context or {}
    fallback = _heuristic_document_type(first_page_text, suggested_type=suggested_type)
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    result = dict(fallback)

    if api_key and Anthropic and first_page_text:
        prompt = (
            "Analyze this document text and identify what type it is.\n\n"
            "Text from first page:\n"
            f"{first_page_text[:9000]}\n\n"
            "Transaction context:\n"
            f"- Property: {context.get('property_address') or 'Unknown'}\n"
            f"- Buyer: {context.get('buyer_name') or 'Unknown'}\n"
            f"- Closing: {context.get('closing_date') or 'Unknown'}\n\n"
            "Return JSON:\n"
            "{\n"
            "  'type': 'inspection_report|earnest_receipt|appraisal|title_commitment|hoa_docs|survey|option_receipt|seller_disclosure|loan_approval|insurance_binder|settlement_statement|other|unknown',\n"
            "  'confidence': 0-100,\n"
            "  'key_info_extracted': {...}\n"
            "}\n\n"
            "If confidence < 70%, return 'unknown'."
        )
        try:
            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model=(os.getenv("DOCUMENT_CLASSIFIER_MODEL") or "claude-sonnet-4-20250514"),
                max_tokens=800,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            payload = _extract_json_from_text(_extract_claude_text_response(response))
            if isinstance(payload, dict):
                parsed_type = normalize_document_type(payload.get("type"), fallback=result.get("type") or "other")
                try:
                    parsed_confidence = int(payload.get("confidence"))
                except (TypeError, ValueError):
                    parsed_confidence = int(result.get("confidence") or 0)
                parsed_confidence = max(0, min(parsed_confidence, 100))
                extracted = payload.get("key_info_extracted")
                if not isinstance(extracted, dict):
                    extracted = {}
                result = {
                    "type": parsed_type,
                    "confidence": parsed_confidence,
                    "key_info_extracted": extracted,
                    "source": "claude",
                }
        except Exception:
            result = dict(fallback)

    learned = _learned_type_override(result.get("type"))
    if learned:
        result["type"] = learned["type"]
        result["confidence"] = min(100, int(result.get("confidence") or 0) + int(learned["confidence_boost"]))
        result["learned_override"] = True

    result["type"] = normalize_document_type(result.get("type"), fallback="unknown")
    result["confidence"] = max(0, min(int(result.get("confidence") or 0), 100))
    if result["confidence"] < 70:
        result["type"] = "unknown"
    return result


def _safe_property_short(property_address):
    raw = (property_address or "property").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        raw = "property"
    return raw[:36]


def build_smart_filename(document_type, property_address, extension):
    normalized_type = normalize_document_type(document_type, fallback="unknown")
    safe_property = _safe_property_short(property_address)
    ext = (extension or "pdf").strip().lower() or "pdf"
    return f"{normalized_type}_{safe_property}_{date.today().isoformat()}.{ext}"


def process_uploaded_document(
    file_bytes,
    transaction_id,
    uploaded_by,
    original_filename,
    extension,
    transaction_context,
    suggested_document_type="other",
):
    """
    Smart pre-S3 processing:
    1) first-page extraction
    2) AI/heuristic type identification
    3) smart filename generation
    4) upload to S3 under improved name
    """
    _ = uploaded_by  # reserved for future routing/analytics
    first_page_text = extract_text_from_first_page(file_bytes, extension)
    doc_analysis = identify_document_type(
        first_page_text=first_page_text,
        transaction_context=transaction_context or {},
        suggested_type=suggested_document_type,
    )

    predicted_type = normalize_document_type(doc_analysis.get("type"), fallback="unknown")
    final_document_type = predicted_type
    if predicted_type == "unknown":
        fallback = normalize_document_type(suggested_document_type, fallback="other")
        if fallback not in {"", "unknown"}:
            final_document_type = fallback

    generated_filename = build_smart_filename(
        document_type=final_document_type,
        property_address=(transaction_context or {}).get("property_address") or "",
        extension=extension,
    )
    content_stream = io.BytesIO(bytes(file_bytes))
    s3_key = upload_document(
        file=content_stream,
        transaction_id=transaction_id,
        document_type=final_document_type,
        filename=generated_filename,
    )

    return {
        "success": bool(s3_key),
        "s3_key": s3_key,
        "document_type": final_document_type,
        "predicted_type": predicted_type,
        "analysis": doc_analysis,
        "first_page_text": first_page_text,
        "filename": generated_filename if s3_key else (original_filename or generated_filename),
    }


def extract_earnest_amount(first_page_text, key_info_extracted=None):
    """Extract likely earnest amount from first-page text."""
    extracted = key_info_extracted if isinstance(key_info_extracted, dict) else {}
    for key in ("earnest_amount", "amount", "deposit_amount"):
        raw = extracted.get(key)
        if raw is None:
            continue
        try:
            amount = float(str(raw).replace("$", "").replace(",", "").strip())
            if amount > 0:
                return round(amount, 2)
        except (TypeError, ValueError):
            continue

    text = (first_page_text or "").lower()
    earnest_window = ""
    match = re.search(r"earnest.{0,120}", text, flags=re.IGNORECASE)
    if match:
        earnest_window = match.group(0)

    amount_pattern = r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})|[0-9]+(?:\.[0-9]{1,2})?)"
    candidates = []
    target_texts = [earnest_window] if earnest_window else [text]
    for target in target_texts:
        for amount_match in re.finditer(amount_pattern, target):
            raw = amount_match.group(1).replace(",", "")
            try:
                amount = float(raw)
            except ValueError:
                continue
            if 10 <= amount <= 250000:
                candidates.append(amount)
    if not candidates:
        return None
    return round(min(candidates), 2)

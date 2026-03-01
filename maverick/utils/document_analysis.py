import re
from typing import Dict, List, Tuple

from pdf2image import convert_from_path
from PyPDF2 import PdfReader
import pdfplumber
import pytesseract


TOTAL_METHOD_COUNT = 3
MIN_AGREEMENT_TO_FLAG = 2


def _clean_match_text(raw_value: str) -> str:
    text = re.sub(r"\s+", " ", (raw_value or "").strip())
    return text[:280]


def _normalize_match_key(raw_value: str) -> str:
    lowered = (raw_value or "").lower()
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return re.sub(r"[^a-z0-9$.\s/-]", "", lowered)


def _confidence_from_count(agreement_count: int) -> str:
    if agreement_count >= 3:
        return "high"
    if agreement_count == 2:
        return "medium"
    return "low"


def _extract_amounts(text: str) -> List[float]:
    amounts = []
    for match in re.finditer(r"\$[\s]*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", text or ""):
        numeric = match.group(1).replace(",", "")
        try:
            amounts.append(float(numeric))
        except ValueError:
            continue
    return amounts


def _method_texts_from_pdf(pdf_path: str, max_pages: int = 15) -> Tuple[Dict[str, str], Dict[str, str]]:
    texts = {"method1_ocr": "", "method2_pypdf": "", "method3_pdfplumber": ""}
    errors = {}

    try:
        images = convert_from_path(pdf_path, first_page=1, last_page=max_pages)
        ocr_chunks = []
        for page_index, image in enumerate(images, start=1):
            ocr_chunks.append(f"\n--- PAGE {page_index} ---\n{pytesseract.image_to_string(image) or ''}")
        texts["method1_ocr"] = "\n".join(ocr_chunks)
    except Exception as exc:
        errors["method1_ocr"] = str(exc)

    try:
        reader = PdfReader(pdf_path)
        pypdf_chunks = []
        for page in reader.pages[:max_pages]:
            pypdf_chunks.append(page.extract_text() or "")
        texts["method2_pypdf"] = "\n".join(pypdf_chunks)
    except Exception as exc:
        errors["method2_pypdf"] = str(exc)

    try:
        plumber_chunks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:max_pages]:
                plumber_chunks.append(page.extract_text(layout=True) or "")
        texts["method3_pdfplumber"] = "\n".join(plumber_chunks)
    except Exception as exc:
        errors["method3_pdfplumber"] = str(exc)

    return texts, errors


def _collect_pattern_matches(method_texts: Dict[str, str], pattern: str) -> Dict[str, List[dict]]:
    candidates = {}
    low_confidence_count = 0

    for method_name, text in method_texts.items():
        if not text:
            continue
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw_snippet = match.group(1) if match.lastindex else match.group(0)
            snippet = _clean_match_text(raw_snippet)
            if not snippet:
                continue
            key = _normalize_match_key(snippet)
            if not key:
                continue
            if key not in candidates:
                candidates[key] = {
                    "text": snippet,
                    "methods": set(),
                }
            candidates[key]["methods"].add(method_name)

    results = []
    for value in candidates.values():
        agreement_count = len(value["methods"])
        confidence = _confidence_from_count(agreement_count)
        item = {
            "text": value["text"],
            "agreement": f"{agreement_count}/{TOTAL_METHOD_COUNT}",
            "confidence": confidence,
            "method_count": agreement_count,
        }
        if agreement_count >= MIN_AGREEMENT_TO_FLAG:
            results.append(item)
        else:
            low_confidence_count += 1

    results.sort(key=lambda item: (-item["method_count"], item["text"]))
    return {"flagged": results, "ignored_low_confidence_count": low_confidence_count}


def _confidence_summary(items: List[dict]) -> Dict[str, int]:
    summary = {"high": 0, "medium": 0, "low": 0}
    for item in items:
        confidence = (item.get("confidence") or "").lower()
        if confidence in summary:
            summary[confidence] += 1
    return summary


def _best_single_item(items: List[dict]):
    return items[0] if items else None


def analyze_hoa_documents(pdf_path):
    """
    Scan HOA documents for critical information.
    Returns dict with extracted data and action items.
    """
    method_texts, method_errors = _method_texts_from_pdf(pdf_path, max_pages=25)

    patterns = {
        "monthly_dues": r"([^\n\.]{0,80}\$\s?\d[\d,]*(?:\.\d{1,2})?\s*(?:per month|monthly|/month)[^\n\.]{0,60})",
        "special_assessment": r"([^\n\.]{0,90}special assessment[^\n\.]{0,160}\$\s?\d[\d,]*(?:\.\d{1,2})?[^\n\.]{0,60})",
        "violations": r"([^\n\.]{0,90}(?:violation|non-compliance|breach)[^\n\.]{0,160})",
        "restrictions": r"([^\n\.]{0,90}(?:restriction|prohibited|not allowed)[^\n\.]{0,160})",
        "approval_required": r"([^\n\.]{0,90}(?:approval required|must approve|board approval)[^\n\.]{0,160})",
        "fees_owed": r"([^\n\.]{0,90}(?:outstanding|past due|owed)[^\n\.]{0,160}\$\s?\d[\d,]*(?:\.\d{1,2})?[^\n\.]{0,60})",
    }

    monthly_dues_matches = _collect_pattern_matches(method_texts, patterns["monthly_dues"])
    special_assessment_matches = _collect_pattern_matches(method_texts, patterns["special_assessment"])
    violation_matches = _collect_pattern_matches(method_texts, patterns["violations"])
    restriction_matches = _collect_pattern_matches(method_texts, patterns["restrictions"])
    approval_matches = _collect_pattern_matches(method_texts, patterns["approval_required"])
    fees_owed_matches = _collect_pattern_matches(method_texts, patterns["fees_owed"])

    monthly_dues = _best_single_item(monthly_dues_matches["flagged"])
    outstanding_fees = _best_single_item(fees_owed_matches["flagged"])
    special_assessments = special_assessment_matches["flagged"]
    violations = violation_matches["flagged"]
    restrictions = restriction_matches["flagged"]
    approval_required = approval_matches["flagged"]

    special_amounts = []
    for item in special_assessments:
        special_amounts.extend(_extract_amounts(item.get("text", "")))
    max_special_assessment = max(special_amounts) if special_amounts else 0

    action_items = []
    if special_assessments:
        amount_label = f"${max_special_assessment:,.0f}" if max_special_assessment else "unknown amount"
        action_items.append(
            {
                "type": "alert_margaret",
                "priority": "high",
                "immediate": max_special_assessment > 3000,
                "message": f"HOA special assessment of {amount_label} found - notify agent",
            }
        )

    if violations:
        action_items.append(
            {
                "type": "create_task",
                "task": "Review HOA violations with seller",
                "priority": "high",
                "due_days": 2,
            }
        )

    if approval_required:
        action_items.append(
            {
                "type": "create_task",
                "task": "Confirm HOA approval requirements with buyer/agent",
                "priority": "medium",
                "due_days": 4,
            }
        )

    all_items = (
        ([monthly_dues] if monthly_dues else [])
        + special_assessments
        + violations
        + restrictions
        + approval_required
        + ([outstanding_fees] if outstanding_fees else [])
    )

    return {
        "monthly_dues": monthly_dues,
        "special_assessments": special_assessments,
        "violations": violations,
        "restrictions": restrictions,
        "approval_required": approval_required,
        "outstanding_fees": outstanding_fees,
        "action_items": action_items,
        "confidence_summary": _confidence_summary(all_items),
        "ignored_low_confidence_count": (
            monthly_dues_matches["ignored_low_confidence_count"]
            + special_assessment_matches["ignored_low_confidence_count"]
            + violation_matches["ignored_low_confidence_count"]
            + restriction_matches["ignored_low_confidence_count"]
            + approval_matches["ignored_low_confidence_count"]
            + fees_owed_matches["ignored_low_confidence_count"]
        ),
        "method_errors": method_errors,
    }


def analyze_inspection_report(pdf_path):
    """
    Scan inspection report for repair items and safety issues.
    Returns dict with findings and action items.
    """
    method_texts, method_errors = _method_texts_from_pdf(pdf_path, max_pages=35)

    patterns = {
        "major_defects": r"([^\n\.]{0,90}(?:major|significant|safety|hazard|structural)[^\n\.]{0,180})",
        "repair_items": r"([^\n\.]{0,90}(?:repair|replace|fix|damaged|broken)[^\n\.]{0,180})",
        "roof_issues": r"([^\n\.]{0,90}roof[^\n\.]{0,140}(?:leak|damage|repair)[^\n\.]{0,80})",
        "hvac_issues": r"([^\n\.]{0,90}(?:HVAC|heating|cooling|air condition)[^\n\.]{0,140})",
        "plumbing_issues": r"([^\n\.]{0,90}(?:plumb|water|leak|pipe)[^\n\.]{0,160})",
        "electrical_issues": r"([^\n\.]{0,90}(?:electric|wiring|panel|outlet)[^\n\.]{0,160})",
        "foundation_issues": r"([^\n\.]{0,90}(?:foundation|crack|settlement|structural)[^\n\.]{0,160})",
        "estimated_costs": r"([^\n\.]{0,90}\$\s?\d[\d,]*(?:\.\d{1,2})?\s*(?:to repair|estimate|cost)[^\n\.]{0,80})",
    }

    major_defects_matches = _collect_pattern_matches(method_texts, patterns["major_defects"])
    repair_matches = _collect_pattern_matches(method_texts, patterns["repair_items"])
    roof_matches = _collect_pattern_matches(method_texts, patterns["roof_issues"])
    hvac_matches = _collect_pattern_matches(method_texts, patterns["hvac_issues"])
    plumbing_matches = _collect_pattern_matches(method_texts, patterns["plumbing_issues"])
    electrical_matches = _collect_pattern_matches(method_texts, patterns["electrical_issues"])
    foundation_matches = _collect_pattern_matches(method_texts, patterns["foundation_issues"])
    estimate_matches = _collect_pattern_matches(method_texts, patterns["estimated_costs"])

    major_defects = major_defects_matches["flagged"]
    repair_items = repair_matches["flagged"]
    roof_issues = roof_matches["flagged"]
    hvac_issues = hvac_matches["flagged"]
    plumbing_issues = plumbing_matches["flagged"]
    electrical_issues = electrical_matches["flagged"]
    foundation_issues = foundation_matches["flagged"]
    estimate_items = estimate_matches["flagged"]

    safety_issues = []
    for item in major_defects + electrical_issues + foundation_issues:
        snippet = (item.get("text") or "").lower()
        if any(keyword in snippet for keyword in ("safety", "hazard", "electrical", "foundation", "structural")):
            if item not in safety_issues:
                safety_issues.append(item)

    estimated_cost_values = []
    for item in estimate_items:
        estimated_cost_values.extend(_extract_amounts(item.get("text", "")))
    estimated_repair_cost = max(estimated_cost_values) if estimated_cost_values else None

    action_items = []
    if major_defects:
        action_items.append(
            {
                "type": "alert_margaret",
                "priority": "critical",
                "immediate": bool(safety_issues),
                "message": f"{len(major_defects)} major defects found - review urgently",
            }
        )
        action_items.append(
            {
                "type": "create_task",
                "task": "Discuss inspection repairs with buyer and seller",
                "priority": "high",
                "due_days": 2,
            }
        )

    if len(repair_items) > 10:
        action_items.append(
            {
                "type": "alert_margaret",
                "priority": "medium",
                "immediate": False,
                "message": f"{len(repair_items)} repair items - may need negotiation",
            }
        )

    if safety_issues:
        action_items.append(
            {
                "type": "alert_margaret",
                "priority": "critical",
                "immediate": True,
                "message": "Inspection report includes safety issues - immediate review required",
            }
        )

    if estimated_repair_cost and estimated_repair_cost > 10000:
        action_items.append(
            {
                "type": "alert_margaret",
                "priority": "high",
                "immediate": True,
                "message": f"Estimated repair costs exceed $10,000 (${estimated_repair_cost:,.0f})",
            }
        )

    all_items = (
        major_defects
        + repair_items
        + roof_issues
        + hvac_issues
        + plumbing_issues
        + electrical_issues
        + foundation_issues
        + estimate_items
    )

    return {
        "major_defects": major_defects,
        "repair_items": repair_items,
        "roof_issues": roof_issues,
        "hvac_issues": hvac_issues,
        "plumbing_issues": plumbing_issues,
        "electrical_issues": electrical_issues,
        "foundation_issues": foundation_issues,
        "estimated_repair_cost": estimated_repair_cost,
        "estimated_cost_evidence": estimate_items,
        "safety_issues": safety_issues,
        "action_items": action_items,
        "confidence_summary": _confidence_summary(all_items),
        "ignored_low_confidence_count": (
            major_defects_matches["ignored_low_confidence_count"]
            + repair_matches["ignored_low_confidence_count"]
            + roof_matches["ignored_low_confidence_count"]
            + hvac_matches["ignored_low_confidence_count"]
            + plumbing_matches["ignored_low_confidence_count"]
            + electrical_matches["ignored_low_confidence_count"]
            + foundation_matches["ignored_low_confidence_count"]
            + estimate_matches["ignored_low_confidence_count"]
        ),
        "method_errors": method_errors,
    }

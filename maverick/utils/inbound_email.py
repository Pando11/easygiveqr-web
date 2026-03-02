import re


EMAIL_REGEX = re.compile(r"[A-Z0-9._%+\-']+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)

INBOUND_CATEGORY_PATTERNS = {
    "inspection": (
        "inspection",
        "inspector",
        "foundation",
        "structural",
        "engineer",
        "repair",
        "roof",
        "hvac",
        "plumbing",
        "electrical",
    ),
    "appraisal": (
        "appraisal",
        "appraiser",
        "appraised",
        "value",
        "comparable",
    ),
    "repairs": (
        "repair",
        "fix",
        "damaged",
        "broken",
        "issue",
    ),
    "closing": (
        "closing",
        "funding",
        "title",
        "wire",
        "final walkthrough",
        "walk-through",
    ),
}

HIGH_URGENCY_KEYWORDS = {
    "urgent",
    "asap",
    "immediately",
    "critical",
    "major",
    "problem",
    "issue",
    "structural",
    "foundation",
    "cold feet",
    "cancel",
    "termination",
}

MEDIUM_URGENCY_KEYWORDS = {
    "follow up",
    "follow-up",
    "update needed",
    "needs awareness",
    "review",
    "delay",
    "question",
    "concern",
}

ACTION_REQUIRED_KEYWORDS = {
    "need",
    "needed",
    "must",
    "required",
    "please",
    "call",
    "coordinate",
    "review",
    "action",
}


def extract_email_address(raw_value):
    """Extract and normalize one email from text like 'Name <email@host>'."""
    value = (raw_value or "").strip()
    if not value:
        return ""
    matches = EMAIL_REGEX.findall(value)
    if not matches:
        return value.lower()
    return matches[0].lower()


def split_recipient_addresses(raw_value):
    """Return normalized email addresses from mixed recipient payloads."""
    if raw_value is None:
        return []
    if isinstance(raw_value, (list, tuple, set)):
        values = " ".join(str(item) for item in raw_value)
    else:
        values = str(raw_value)
    matches = [email.lower() for email in EMAIL_REGEX.findall(values or "")]
    unique = []
    for email in matches:
        if email not in unique:
            unique.append(email)
    return unique


def parse_transaction_alias(address, domain):
    """Parse `transaction-<id>-<role>@<domain>` style alias addresses."""
    safe_address = (address or "").strip().lower()
    safe_domain = (domain or "").strip().lower().lstrip("@")
    if "@" not in safe_address or not safe_domain:
        return None
    local_part, host = safe_address.split("@", 1)
    if host != safe_domain:
        return None

    match = re.fullmatch(r"transaction-(\d+)-(buyer|seller|lender)", local_part)
    if not match:
        return None
    return {
        "transaction_id": int(match.group(1)),
        "mailbox_role": match.group(2),
        "mailbox_address": safe_address,
    }


def _contains_phrase(text, phrase):
    return phrase in text


def _detect_category(text):
    for category, keywords in INBOUND_CATEGORY_PATTERNS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "general"


def _urgency_from_text(text):
    score = 0
    matched_high = []
    matched_medium = []
    for keyword in HIGH_URGENCY_KEYWORDS:
        if keyword in text:
            score += 2
            matched_high.append(keyword)
    for keyword in MEDIUM_URGENCY_KEYWORDS:
        if keyword in text:
            score += 1
            matched_medium.append(keyword)

    if score >= 4:
        urgency = "high"
    elif score >= 2:
        urgency = "medium"
    else:
        urgency = "low"
    return urgency, matched_high, matched_medium


def classify_inbound_email(subject, body_text, sender_role="external"):
    """
    Analyze inbound email content for urgency, category, and actions.

    This is a deterministic rules engine intended for routing safety.
    """
    subject_text = (subject or "").strip()
    body = (body_text or "").strip()
    full_text = f"{subject_text}\n{body}".strip().lower()

    category = _detect_category(full_text)
    urgency, matched_high, matched_medium = _urgency_from_text(full_text)
    action_required = any(keyword in full_text for keyword in ACTION_REQUIRED_KEYWORDS)

    analysis = {
        "urgency": urgency,
        "category": category,
        "action_required": bool(action_required),
        "sensitive_content": False,
        "at_risk": False,
        "status_update_hint": "",
        "recommended_task": "",
        "margaret_alert": "",
        "matched_high_keywords": matched_high,
        "matched_medium_keywords": matched_medium,
    }

    if _contains_phrase(full_text, "appraisal ordered"):
        analysis["category"] = "appraisal"
        analysis["urgency"] = "low"
        analysis["action_required"] = False
        analysis["status_update_hint"] = "appraisal_ordered"
        analysis["recommended_task"] = ""
        analysis["margaret_alert"] = ""
        return analysis

    if sender_role == "buyer" and (
        _contains_phrase(full_text, "cold feet")
        or _contains_phrase(full_text, "not sure about this property")
        or _contains_phrase(full_text, "want to back out")
        or _contains_phrase(full_text, "thinking of cancelling")
    ):
        analysis["category"] = "closing"
        analysis["urgency"] = "high"
        analysis["action_required"] = True
        analysis["sensitive_content"] = True
        analysis["at_risk"] = True
        analysis["recommended_task"] = "Call buyer immediately to address concerns and stabilize transaction."
        analysis["margaret_alert"] = "⚠️ Buyer expressing concerns - call needed"
        return analysis

    if (
        (_contains_phrase(full_text, "major foundation") or _contains_phrase(full_text, "foundation issue"))
        and (_contains_phrase(full_text, "structural") or _contains_phrase(full_text, "engineer"))
    ) or _contains_phrase(full_text, "structural engineer"):
        analysis["category"] = "inspection"
        analysis["urgency"] = "high"
        analysis["action_required"] = True
        analysis["recommended_task"] = "Coordinate structural engineer inspection."
        analysis["margaret_alert"] = "🚨 Inspection issue - structural engineer needed"
        return analysis

    if analysis["urgency"] == "high" and analysis["action_required"] and not analysis["margaret_alert"]:
        category_label = analysis["category"].replace("_", " ")
        analysis["margaret_alert"] = f"🚨 High urgency {category_label} email - review now"
    elif analysis["urgency"] == "medium" and analysis["action_required"]:
        analysis["recommended_task"] = "Review inbound update and confirm next coordination step."

    return analysis

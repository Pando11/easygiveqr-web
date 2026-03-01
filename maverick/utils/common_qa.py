from __future__ import annotations

import hashlib
import json
import math
import os
import re
from difflib import SequenceMatcher
from collections import defaultdict
from datetime import date

from utils.db import execute_query


def _int_env(name, default_value):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default_value)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default_value)


def _float_env(name, default_value):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return float(default_value)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default_value)


EMBEDDING_DIMENSIONS = max(32, min(_int_env("COMMON_QA_EMBEDDING_DIMENSIONS", 128), 512))
SIMILARITY_MATCH_THRESHOLD = max(0.5, min(_float_env("COMMON_QA_SIMILARITY_THRESHOLD", 0.85), 0.99))
AUTO_ANSWER_CONFIDENCE_THRESHOLD = max(50.0, min(_float_env("COMMON_QA_AUTO_CONFIDENCE", 95.0), 100.0))
SUGGEST_CONFIDENCE_THRESHOLD = max(40.0, min(_float_env("COMMON_QA_SUGGEST_CONFIDENCE", 75.0), 100.0))
AUTO_ENABLE_REUSE_COUNT = max(1, min(_int_env("COMMON_QA_AUTO_ENABLE_REUSE_COUNT", 5), 100))

COMMON_QA_CATEGORY_OPTIONS = [
    ("closing_procedures", "Closing procedures"),
    ("document_requirements", "Document requirements"),
    ("timeline_questions", "Timeline questions"),
    ("payment_questions", "Payment questions"),
    ("title_escrow_questions", "Title/escrow questions"),
    ("inspection_appraisal_questions", "Inspection/appraisal questions"),
    ("general", "General"),
]

_CATEGORY_KEYWORDS = {
    "closing_procedures": (
        "closing",
        "close",
        "keys",
        "funding",
        "final walk",
        "walk-through",
        "walk through",
        "closing day",
        "what do i bring",
    ),
    "document_requirements": (
        "document",
        "paperwork",
        "upload",
        "send",
        "required",
        "need to provide",
        "disclosure",
        "addendum",
        "form",
    ),
    "timeline_questions": (
        "timeline",
        "when",
        "date",
        "deadline",
        "how long",
        "days",
        "schedule",
        "status",
    ),
    "payment_questions": (
        "payment",
        "paid",
        "cash to close",
        "wire",
        "cashier",
        "earnest",
        "option fee",
        "amount",
        "cost",
    ),
    "title_escrow_questions": (
        "title",
        "escrow",
        "settlement",
        "commitment",
        "officer",
        "escrow account",
        "title company",
    ),
    "inspection_appraisal_questions": (
        "inspection",
        "inspector",
        "appraisal",
        "appraiser",
        "repairs",
        "foundation",
        "roof",
    ),
}

_CATEGORY_LOOKUP = {key: label for key, label in COMMON_QA_CATEGORY_OPTIONS}

_COMMON_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "to",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "your",
}

_TOKEN_SYNONYMS = {
    "appraised": "appraisal",
    "appraiser": "appraisal",
    "appraising": "appraisal",
    "close": "closing",
    "closed": "closing",
    "closingday": "closing",
    "docs": "documents",
    "doc": "documents",
    "paperwork": "documents",
    "escrow": "title",
    "fees": "fee",
    "funded": "funding",
    "funds": "funding",
    "inspector": "inspection",
    "inspections": "inspection",
    "repairs": "repair",
    "requirement": "required",
    "requirements": "required",
    "settlement": "closing",
    "timeline": "deadline",
    "timelines": "deadline",
    "titlecompany": "title",
    "wiretransfer": "wire",
}


def _safe_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_common_qa_category(raw_value, fallback="general"):
    normalized = (raw_value or "").strip().lower().replace(" ", "_")
    if normalized in _CATEGORY_LOOKUP:
        return normalized
    return fallback


def common_qa_category_label(category):
    key = normalize_common_qa_category(category, fallback="general")
    return _CATEGORY_LOOKUP.get(key, "General")


def infer_common_qa_category(question_text):
    text = _safe_text(question_text).lower()
    if not text:
        return "general"
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "general"


def _normalize_token(token):
    cleaned = re.sub(r"[^a-z0-9]", "", (token or "").strip().lower())
    if not cleaned:
        return ""
    if cleaned in _TOKEN_SYNONYMS:
        return _TOKEN_SYNONYMS[cleaned]
    if cleaned.endswith("ing") and len(cleaned) > 5:
        cleaned = cleaned[:-3]
    elif cleaned.endswith("ed") and len(cleaned) > 4:
        cleaned = cleaned[:-2]
    elif cleaned.endswith("es") and len(cleaned) > 4:
        cleaned = cleaned[:-2]
    elif cleaned.endswith("s") and len(cleaned) > 3:
        cleaned = cleaned[:-1]
    if cleaned in _TOKEN_SYNONYMS:
        return _TOKEN_SYNONYMS[cleaned]
    return cleaned


def _tokenize_for_embedding(text):
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    tokens = []
    for raw_word in words:
        token = _normalize_token(raw_word)
        if not token or token in _COMMON_STOPWORDS or len(token) <= 1:
            continue
        tokens.append(token)
    return tokens


def generate_question_embedding(question_text, dimensions=EMBEDDING_DIMENSIONS):
    """
    Deterministic local text embedding.

    This avoids hard dependency on a paid embedding API while still enabling
    semantic-ish matching for frequently repeated operational questions.
    """
    text = _safe_text(question_text).lower()
    vector = [0.0] * int(dimensions)
    if not text:
        return vector

    tokens = _tokenize_for_embedding(text)
    if not tokens:
        return vector

    weighted_tokens = list(tokens)
    for idx in range(len(tokens) - 1):
        weighted_tokens.append(f"{tokens[idx]}_{tokens[idx + 1]}")

    for token in weighted_tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        weight = 1.35 if "_" in token else 1.0
        vector[bucket] += weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return [0.0] * int(dimensions)
    return [round(value / norm, 8) for value in vector]


def _embedding_literal(embedding):
    return "[" + ",".join(f"{float(value):.8f}" for value in (embedding or [])) + "]"


def parse_embedding(raw_value):
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [float(value) for value in raw_value]
    if isinstance(raw_value, tuple):
        return [float(value) for value in raw_value]
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        if text.startswith("{") and text.endswith("}"):
            # Postgres float array text.
            parts = [part.strip() for part in text[1:-1].split(",") if part.strip()]
            parsed = []
            for part in parts:
                try:
                    parsed.append(float(part))
                except (TypeError, ValueError):
                    continue
            return parsed
        if text.startswith("[") and text.endswith("]"):
            parts = [part.strip() for part in text[1:-1].split(",") if part.strip()]
            parsed = []
            for part in parts:
                try:
                    parsed.append(float(part))
                except (TypeError, ValueError):
                    continue
            return parsed
        try:
            maybe = json.loads(text)
            if isinstance(maybe, list):
                return [float(value) for value in maybe]
        except Exception:
            return []
    return []


def cosine_similarity(vector_a, vector_b):
    a = list(vector_a or [])
    b = list(vector_b or [])
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        min_len = min(len(a), len(b))
        a = a[:min_len]
        b = b[:min_len]
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return max(min(dot / (norm_a * norm_b), 1.0), -1.0)


def blended_similarity(source_text, target_text, source_embedding, target_embedding):
    """
    Hybrid similarity anchored on cosine, with lexical overlap boost.

    The system still uses cosine as the base semantic metric but combines
    it with token overlap and sequence ratio so practical TC paraphrases
    clear operational thresholds more reliably.
    """
    raw_cosine = cosine_similarity(source_embedding, target_embedding)
    source_tokens = set(_tokenize_for_embedding(source_text))
    target_tokens = set(_tokenize_for_embedding(target_text))
    if source_tokens or target_tokens:
        token_overlap = len(source_tokens.intersection(target_tokens)) / max(len(source_tokens.union(target_tokens)), 1)
    else:
        token_overlap = 0.0
    seq_ratio = SequenceMatcher(None, _safe_text(source_text).lower(), _safe_text(target_text).lower()).ratio()
    category_bonus = 0.0
    if infer_common_qa_category(source_text) == infer_common_qa_category(target_text):
        category_bonus = 0.04
    adjusted = max(
        raw_cosine,
        min(1.0, (raw_cosine * 0.50) + (token_overlap * 0.68) + (seq_ratio * 0.22) + category_bonus),
    )
    return {
        "adjusted": adjusted,
        "raw_cosine": raw_cosine,
        "token_overlap": token_overlap,
        "sequence_ratio": seq_ratio,
    }


def _embedding_column_kind():
    rows = execute_query(
        """
        SELECT data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'common_qa'
          AND column_name = 'question_embedding'
        LIMIT 1
        """,
        fetch=True,
    ) or []
    if not rows:
        return "vector"
    row = rows[0]
    udt_name = (row.get("udt_name") or "").strip().lower()
    if udt_name == "vector":
        return "vector"
    if udt_name in {"_float8", "_float4"}:
        return "array"
    return "vector"


def ensure_common_qa_tables():
    """Create smart Q&A tables and indexes."""
    execute_query("CREATE EXTENSION IF NOT EXISTS vector")
    created = execute_query(
        f"""
        CREATE TABLE IF NOT EXISTS common_qa (
            id SERIAL PRIMARY KEY,
            question_text TEXT NOT NULL,
            question_embedding VECTOR({EMBEDDING_DIMENSIONS}),
            answer_text TEXT NOT NULL,
            transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
            asked_by_party VARCHAR(50),
            times_reused INT DEFAULT 0,
            auto_answer BOOLEAN DEFAULT FALSE,
            category VARCHAR(50),
            last_used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    if not created:
        # Fallback when pgvector extension is unavailable on the DB.
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS common_qa (
                id SERIAL PRIMARY KEY,
                question_text TEXT NOT NULL,
                question_embedding DOUBLE PRECISION[],
                answer_text TEXT NOT NULL,
                transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
                asked_by_party VARCHAR(50),
                times_reused INT DEFAULT 0,
                auto_answer BOOLEAN DEFAULT FALSE,
                category VARCHAR(50),
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    execute_query(
        """
        CREATE TABLE IF NOT EXISTS common_qa_events (
            id SERIAL PRIMARY KEY,
            common_qa_id INT REFERENCES common_qa(id) ON DELETE SET NULL,
            transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
            channel VARCHAR(20),
            event_type VARCHAR(40) NOT NULL,
            asked_by_party VARCHAR(50),
            question_text TEXT,
            answer_text TEXT,
            similarity_score DECIMAL(6,4),
            confidence_score DECIMAL(5,2),
            auto_answer BOOLEAN DEFAULT FALSE,
            metadata JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    execute_query("ALTER TABLE common_qa_events ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb")
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_common_qa_category_reuse
        ON common_qa(category, times_reused DESC, updated_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_common_qa_auto_answer
        ON common_qa(auto_answer, times_reused DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_common_qa_transaction
        ON common_qa(transaction_id, updated_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_common_qa_events_created
        ON common_qa_events(created_at DESC, event_type)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_common_qa_events_common_qa
        ON common_qa_events(common_qa_id, created_at DESC)
        """
    )


def fetch_common_qa_row(common_qa_id):
    ensure_common_qa_tables()
    rows = execute_query(
        """
        SELECT
            id, question_text, question_embedding, answer_text,
            transaction_id, asked_by_party, times_reused, auto_answer, category,
            last_used_at, created_at, updated_at
        FROM common_qa
        WHERE id = %s
        LIMIT 1
        """,
        (common_qa_id,),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    row["question_embedding"] = parse_embedding(row.get("question_embedding"))
    row["category"] = normalize_common_qa_category(row.get("category"), fallback="general")
    row["category_label"] = common_qa_category_label(row["category"])
    return row


def fetch_common_qa_rows(limit=300, category=None, search_text=""):
    ensure_common_qa_tables()
    filters = []
    params = []
    if category:
        filters.append("LOWER(COALESCE(category, 'general')) = %s")
        params.append(normalize_common_qa_category(category))
    if search_text:
        filters.append("(LOWER(question_text) LIKE %s OR LOWER(answer_text) LIKE %s)")
        wildcard = f"%{_safe_text(search_text).lower()}%"
        params.extend([wildcard, wildcard])
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(int(limit))
    rows = execute_query(
        f"""
        SELECT
            id, question_text, question_embedding, answer_text,
            transaction_id, asked_by_party, times_reused, auto_answer, category,
            last_used_at, created_at, updated_at
        FROM common_qa
        {where_clause}
        ORDER BY times_reused DESC, updated_at DESC, id DESC
        LIMIT %s
        """,
        tuple(params),
        fetch=True,
    ) or []
    for row in rows:
        row["question_embedding"] = parse_embedding(row.get("question_embedding"))
        row["category"] = normalize_common_qa_category(row.get("category"), fallback="general")
        row["category_label"] = common_qa_category_label(row["category"])
    return rows


def find_similar_common_qa(question_text, category_hint=None, asked_by_party=None, limit=180):
    """
    Return best semantic match + scored candidates for one inbound question.
    """
    ensure_common_qa_tables()
    question_clean = _safe_text(question_text)
    if not question_clean:
        return {"question_embedding": [], "best_match": None, "candidates": []}

    question_embedding = generate_question_embedding(question_clean)
    rows = fetch_common_qa_rows(limit=max(int(limit), 1))

    scored = []
    for row in rows:
        embedding = row.get("question_embedding") or []
        if not embedding:
            continue
        blend = blended_similarity(question_clean, row.get("question_text") or "", question_embedding, embedding)
        similarity = float(blend["adjusted"])
        score = {
            "id": row["id"],
            "question_text": row.get("question_text") or "",
            "answer_text": row.get("answer_text") or "",
            "times_reused": int(row.get("times_reused") or 0),
            "auto_answer": bool(row.get("auto_answer")),
            "category": row.get("category") or "general",
            "asked_by_party": row.get("asked_by_party") or "",
            "similarity": round(float(similarity), 4),
            "raw_cosine": round(float(blend["raw_cosine"]), 4),
            "token_overlap": round(float(blend["token_overlap"]), 4),
            "sequence_ratio": round(float(blend["sequence_ratio"]), 4),
            "confidence": round(max(0.0, min(100.0, similarity * 100.0)), 2),
        }
        # Small tie-breakers for same category/party patterns.
        if category_hint and score["category"] == normalize_common_qa_category(category_hint):
            score["confidence"] = min(100.0, score["confidence"] + 2.5)
        if asked_by_party and (score["asked_by_party"] or "").strip().lower() == (asked_by_party or "").strip().lower():
            score["confidence"] = min(100.0, score["confidence"] + 1.5)
        scored.append(score)

    scored.sort(key=lambda item: (item["similarity"], item["times_reused"], item["id"]), reverse=True)
    best = scored[0] if scored else None
    if best and best["similarity"] < SIMILARITY_MATCH_THRESHOLD:
        best = None
    return {
        "question_embedding": question_embedding,
        "best_match": best,
        "candidates": scored[:25],
    }


def evaluate_common_qa_decision(question_text, asked_by_party="", category_hint=""):
    """
    Apply decision thresholds for auto-answer/suggest/none.
    """
    scored = find_similar_common_qa(
        question_text=question_text,
        category_hint=category_hint,
        asked_by_party=asked_by_party,
    )
    match = scored.get("best_match")
    if not match:
        return {
            "decision": "none",
            "confidence": 0.0,
            "similarity": 0.0,
            "match": None,
            "question_embedding": scored.get("question_embedding") or [],
        }

    confidence = float(match.get("confidence") or 0.0)
    decision = "none"
    if confidence > AUTO_ANSWER_CONFIDENCE_THRESHOLD and bool(match.get("auto_answer")):
        decision = "auto_answer"
    elif confidence > SUGGEST_CONFIDENCE_THRESHOLD:
        decision = "suggest"

    return {
        "decision": decision,
        "confidence": confidence,
        "similarity": float(match.get("similarity") or 0.0),
        "match": match,
        "question_embedding": scored.get("question_embedding") or [],
    }


def _db_embedding_value(embedding):
    if _embedding_column_kind() == "array":
        return list(embedding or [])
    return _embedding_literal(embedding or [])


def create_common_qa_entry(
    question_text,
    answer_text,
    transaction_id=None,
    asked_by_party="",
    category="general",
    force_new=False,
):
    ensure_common_qa_tables()
    question_clean = _safe_text(question_text)
    answer_clean = _safe_text(answer_text)
    if not question_clean or not answer_clean:
        return None

    category_key = normalize_common_qa_category(category or infer_common_qa_category(question_clean))
    embedding = generate_question_embedding(question_clean)

    if not force_new:
        duplicate = evaluate_common_qa_decision(
            question_text=question_clean,
            asked_by_party=asked_by_party or "",
            category_hint=category_key,
        )
        match = duplicate.get("match")
        if match and float(duplicate.get("similarity") or 0.0) >= 0.985:
            execute_query(
                """
                UPDATE common_qa
                SET answer_text = %s,
                    transaction_id = COALESCE(%s, transaction_id),
                    asked_by_party = COALESCE(NULLIF(%s, ''), asked_by_party),
                    category = COALESCE(NULLIF(%s, ''), category),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    answer_clean,
                    transaction_id,
                    (asked_by_party or "").strip().lower(),
                    category_key,
                    match["id"],
                ),
            )
            return fetch_common_qa_row(match["id"])

    rows = execute_query(
        """
        INSERT INTO common_qa (
            question_text, question_embedding, answer_text,
            transaction_id, asked_by_party, category, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (
            question_clean,
            _db_embedding_value(embedding),
            answer_clean,
            transaction_id,
            (asked_by_party or "").strip().lower() or None,
            category_key,
        ),
        fetch=True,
    ) or []
    if not rows:
        return None
    return fetch_common_qa_row(rows[0]["id"])


def update_common_qa_entry(common_qa_id, answer_text=None, category=None, auto_answer=None):
    ensure_common_qa_tables()
    existing = fetch_common_qa_row(common_qa_id)
    if not existing:
        return None
    next_answer = _safe_text(answer_text) if answer_text is not None else existing.get("answer_text")
    next_category = (
        normalize_common_qa_category(category, fallback=existing.get("category") or "general")
        if category is not None
        else existing.get("category")
    )
    next_auto = bool(auto_answer) if auto_answer is not None else bool(existing.get("auto_answer"))
    execute_query(
        """
        UPDATE common_qa
        SET answer_text = %s,
            category = %s,
            auto_answer = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (next_answer, next_category, next_auto, common_qa_id),
    )
    return fetch_common_qa_row(common_qa_id)


def increment_common_qa_reuse(common_qa_id, increment_by=1):
    ensure_common_qa_tables()
    rows = execute_query(
        """
        UPDATE common_qa
        SET times_reused = COALESCE(times_reused, 0) + %s,
            auto_answer = CASE
                WHEN COALESCE(times_reused, 0) + %s >= %s THEN TRUE
                ELSE auto_answer
            END,
            last_used_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        RETURNING id
        """,
        (int(increment_by), int(increment_by), AUTO_ENABLE_REUSE_COUNT, common_qa_id),
        fetch=True,
    ) or []
    return fetch_common_qa_row(rows[0]["id"]) if rows else None


def log_common_qa_event(
    event_type,
    common_qa_id=None,
    transaction_id=None,
    channel="email",
    asked_by_party="",
    question_text="",
    answer_text="",
    similarity_score=None,
    confidence_score=None,
    auto_answer=False,
    metadata=None,
):
    ensure_common_qa_tables()
    execute_query(
        """
        INSERT INTO common_qa_events (
            common_qa_id, transaction_id, channel, event_type, asked_by_party,
            question_text, answer_text, similarity_score, confidence_score, auto_answer, metadata, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        """,
        (
            common_qa_id,
            transaction_id,
            (channel or "email")[:20],
            (event_type or "unknown")[:40],
            (asked_by_party or "")[:50] or None,
            _safe_text(question_text)[:1500] or None,
            _safe_text(answer_text)[:4000] or None,
            similarity_score,
            confidence_score,
            bool(auto_answer),
            json.dumps(metadata or {}, default=str),
        ),
    )


def answer_similarity(answer_a, answer_b):
    embedding_a = generate_question_embedding(_safe_text(answer_a), dimensions=96)
    embedding_b = generate_question_embedding(_safe_text(answer_b), dimensions=96)
    return cosine_similarity(embedding_a, embedding_b)


def fetch_common_qa_analytics():
    ensure_common_qa_tables()
    month_start = date.today().replace(day=1)
    events = execute_query(
        """
        SELECT event_type, COUNT(*) AS total
        FROM common_qa_events
        WHERE created_at >= %s
        GROUP BY event_type
        """,
        (month_start,),
        fetch=True,
    ) or []
    event_counts = {row["event_type"]: int(row["total"] or 0) for row in events}

    auto_answers = event_counts.get("auto_answer_sent", 0)
    suggested_used = event_counts.get("suggested_answer_used", 0)
    minutes_saved = (auto_answers * 5) + (suggested_used * 3)
    hours_saved = round(minutes_saved / 60.0, 1)

    top_questions = execute_query(
        """
        SELECT id, question_text, answer_text, category, times_reused, auto_answer, updated_at
        FROM common_qa
        ORDER BY times_reused DESC, updated_at DESC
        LIMIT 12
        """,
        fetch=True,
    ) or []
    for row in top_questions:
        row["category"] = normalize_common_qa_category(row.get("category"), fallback="general")
        row["category_label"] = common_qa_category_label(row["category"])

    monthly_top = execute_query(
        """
        SELECT COALESCE(c.id, 0) AS common_qa_id,
               COALESCE(c.question_text, e.question_text) AS question_text,
               COUNT(*) AS total
        FROM common_qa_events e
        LEFT JOIN common_qa c ON c.id = e.common_qa_id
        WHERE e.created_at >= %s
        GROUP BY COALESCE(c.id, 0), COALESCE(c.question_text, e.question_text)
        ORDER BY total DESC
        LIMIT 10
        """,
        (month_start,),
        fetch=True,
    ) or []

    category_rows = execute_query(
        """
        SELECT COALESCE(category, 'general') AS category, COUNT(*) AS total
        FROM common_qa
        GROUP BY COALESCE(category, 'general')
        ORDER BY total DESC
        """,
        fetch=True,
    ) or []
    category_breakdown = []
    for row in category_rows:
        key = normalize_common_qa_category(row.get("category"), fallback="general")
        category_breakdown.append(
            {
                "category": key,
                "category_label": common_qa_category_label(key),
                "total": int(row.get("total") or 0),
            }
        )

    faq_ready_count = len([row for row in top_questions if int(row.get("times_reused") or 0) >= 3])
    return {
        "month_start": month_start,
        "hours_saved_this_month": hours_saved,
        "minutes_saved_this_month": minutes_saved,
        "auto_answers_this_month": auto_answers,
        "suggested_used_this_month": suggested_used,
        "event_counts": event_counts,
        "top_questions": top_questions,
        "monthly_top_questions": monthly_top,
        "category_breakdown": category_breakdown,
        "faq_suggestion_ready": faq_ready_count >= 4,
    }


def build_agent_faq_draft(limit=12):
    ensure_common_qa_tables()
    rows = execute_query(
        """
        SELECT question_text, answer_text, category, times_reused
        FROM common_qa
        WHERE COALESCE(times_reused, 0) >= 2
        ORDER BY times_reused DESC, updated_at DESC
        LIMIT %s
        """,
        (int(limit),),
        fetch=True,
    ) or []
    if not rows:
        return {"title": "Agent FAQ Draft", "content": "No reusable Q&A entries available yet.", "item_count": 0}

    grouped = defaultdict(list)
    for row in rows:
        category = normalize_common_qa_category(row.get("category"), fallback="general")
        grouped[category].append(row)

    lines = ["# Maverick Agent FAQ (Draft)", ""]
    for category in sorted(grouped.keys()):
        lines.append(f"## {common_qa_category_label(category)}")
        lines.append("")
        for row in grouped[category]:
            lines.append(f"**Q:** {_safe_text(row.get('question_text'))}")
            lines.append("")
            lines.append(f"**A:** {_safe_text(row.get('answer_text'))}")
            lines.append("")
    return {
        "title": "Agent FAQ Draft",
        "content": "\n".join(lines).strip(),
        "item_count": len(rows),
    }


from __future__ import annotations

import base64
import json
import os
import re
import threading
from datetime import date, datetime, timedelta
from urllib.error import URLError
from urllib.request import Request, urlopen

from utils.db import execute_query
from utils.sms import send_sms

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - optional dependency at runtime
    Anthropic = None


VOICE_NOTE_REVIEW_THRESHOLD = 80
DEFAULT_VOICE_NOTE_TYPE = "general_update"
VOICE_NOTE_TYPES = {
    "lender_call",
    "title_call",
    "inspection_update",
    "appraisal_update",
    "buyer_update",
    "seller_update",
    "agent_update",
    "general_update",
}
WORD_DIGIT_MAP = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "to": "2",
    "too": "2",
    "three": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "ate": "8",
    "nine": "9",
}

_VOICE_NOTE_PROCESSING_LOCK = threading.Lock()
_VOICE_NOTE_PROCESSING_ACTIVE = set()


def ensure_voice_note_tables():
    """Create voice-note persistence tables used by Twilio callbacks."""
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS voice_notes (
            id SERIAL PRIMARY KEY,
            call_sid VARCHAR(80),
            recording_sid VARCHAR(80) UNIQUE,
            from_phone VARCHAR(25),
            recording_url TEXT,
            recording_duration_seconds INT DEFAULT 0,
            transcription_text TEXT,
            transcription_source VARCHAR(20),
            parse_payload JSONB DEFAULT '{}'::jsonb,
            confidence_score INT,
            note_type VARCHAR(80),
            transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
            communication_id INT REFERENCES communications(id) ON DELETE SET NULL,
            actions_taken JSONB DEFAULT '{}'::jsonb,
            status VARCHAR(30) DEFAULT 'received',
            review_required BOOLEAN DEFAULT FALSE,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        )
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_notes_recording_sid
        ON voice_notes(recording_sid)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_notes_transaction
        ON voice_notes(transaction_id, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_notes_status
        ON voice_notes(status, created_at DESC)
        """
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_notes_comm
        ON voice_notes(communication_id)
        """
    )


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if value and str(value).startswith("+"):
        return str(value).strip()
    return f"+{digits}" if digits else ""


def _voice_note_transcription_mode():
    mode = (os.getenv("VOICE_NOTE_TRANSCRIPTION_MODE") or "twilio").strip().lower()
    if mode not in {"twilio", "claude"}:
        return "twilio"
    return mode


def _normalize_note_type(note_type):
    normalized = (note_type or "").strip().lower().replace(" ", "_")
    if normalized in VOICE_NOTE_TYPES:
        return normalized
    return DEFAULT_VOICE_NOTE_TYPE


def _sanitize_list(values, max_items=8, max_item_len=220):
    if not isinstance(values, list):
        return []
    cleaned = []
    for item in values:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        if text.lower() in {existing.lower() for existing in cleaned}:
            continue
        cleaned.append(text[:max_item_len])
        if len(cleaned) >= max_items:
            break
    return cleaned


def _extract_response_text(response):
    text_parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", "") == "text":
            text_parts.append(getattr(block, "text", ""))
    return "\n".join(part for part in text_parts if part).strip()


def _extract_json_block(text):
    raw_text = (text or "").strip()
    if not raw_text:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, flags=re.DOTALL)
    if fence_match:
        raw_text = fence_match.group(1).strip()
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = raw_text[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _spoken_digits_to_int(text):
    tokens = [token for token in re.split(r"[^a-z]+", (text or "").lower()) if token]
    if not tokens:
        return None
    digit_chars = []
    for token in tokens:
        if token in WORD_DIGIT_MAP:
            digit_chars.append(WORD_DIGIT_MAP[token])
            continue
        if token.isdigit():
            digit_chars.extend(list(token))
            continue
        break
    if not digit_chars:
        return None
    try:
        return int("".join(digit_chars))
    except ValueError:
        return None


def parse_transaction_id_from_transcript(transcript_text):
    """Extract transaction id from transcript with numeric + spoken-number fallback."""
    text = (transcript_text or "").strip().lower()
    if not text:
        return None

    patterns = [
        r"(?:transaction|txn|tx|file)\s*(?:number|id|#)?\s*[:#-]?\s*(\d{1,8})\b",
        r"\btransaction\s*#\s*(\d{1,8})\b",
        r"\btxn\s*#?\s*(\d{1,8})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            parsed = _safe_int(match.group(1))
            if parsed:
                return parsed

    spoken_match = re.search(
        r"(?:transaction|txn|tx|file)\s*(?:number|id|#)?\s*[:#-]?\s*([a-z0-9\s-]{2,60})",
        text,
    )
    if spoken_match:
        spoken = _spoken_digits_to_int(spoken_match.group(1))
        if spoken:
            return spoken

    standalone_numbers = re.findall(r"\b(\d{1,8})\b", text)
    if len(standalone_numbers) == 1:
        return _safe_int(standalone_numbers[0])
    return None


def _infer_note_type(transcript_text):
    text = (transcript_text or "").lower()
    if any(keyword in text for keyword in ("lender", "loan", "underwriting", "cd ready", "clear to close")):
        return "lender_call"
    if any(keyword in text for keyword in ("title", "title company", "escrow", "file opened")):
        return "title_call"
    if any(keyword in text for keyword in ("inspection", "inspector")):
        return "inspection_update"
    if any(keyword in text for keyword in ("appraisal", "appraiser")):
        return "appraisal_update"
    if "buyer" in text:
        return "buyer_update"
    if "seller" in text:
        return "seller_update"
    if "agent" in text:
        return "agent_update"
    return DEFAULT_VOICE_NOTE_TYPE


def _heuristic_parse_transcript(transcript_text):
    text = re.sub(r"\s+", " ", (transcript_text or "")).strip()
    lower = text.lower()
    transaction_id = parse_transaction_id_from_transcript(text)
    note_type = _infer_note_type(text)

    complete_tasks = []
    create_tasks = []

    if "loan approved" in lower or ("loan" in lower and "approved" in lower):
        complete_tasks.append("Get loan approval")
    if "inspection scheduled" in lower or ("inspection" in lower and "appointment" in lower):
        complete_tasks.append("Schedule home inspection")
    if "title file opened" in lower or ("title" in lower and "file number" in lower):
        complete_tasks.append("Verify title opened")
    if "earnest" in lower and ("received" in lower or "receipt" in lower):
        complete_tasks.append("Verify earnest money receipt")
    if "cd ready" in lower or ("closing disclosure" in lower and "ready" in lower):
        create_tasks.append("Review CD when received")

    explicit_create = re.findall(r"(?:create|add)\s+task[:\s]+([^.;]{4,180})", lower)
    for task_text in explicit_create:
        create_tasks.append(task_text.strip().capitalize())

    explicit_complete = re.findall(r"(?:complete|mark complete)\s+task[:\s]+([^.;]{4,180})", lower)
    for task_text in explicit_complete:
        complete_tasks.append(task_text.strip().capitalize())

    content = text
    confidence = 45
    if transaction_id:
        confidence += 30
    if note_type != DEFAULT_VOICE_NOTE_TYPE:
        confidence += 10
    if len(text.split()) >= 6:
        confidence += 8
    if complete_tasks or create_tasks:
        confidence += 8
    if any(keyword in lower for keyword in ("maybe", "not sure", "unclear")):
        confidence -= 18
    confidence = max(5, min(confidence, 95))

    return {
        "transaction_id": transaction_id,
        "note_type": note_type,
        "content": content,
        "complete_tasks": complete_tasks,
        "create_tasks": create_tasks,
        "confidence": confidence,
        "parser": "heuristic",
    }


def _parse_with_claude(transcript_text):
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key or Anthropic is None:
        return None

    model = (os.getenv("VOICE_NOTE_CLAUDE_MODEL") or "claude-sonnet-4-20250514").strip()
    prompt = (
        "Transcribe this voice note analysis from the provided transcript. "
        "Extract fields and return STRICT JSON only with keys: "
        "transaction_id (int|null), note_type (string), content (string), "
        "complete_tasks (array of strings), create_tasks (array of strings), confidence (0-100 integer). "
        "If uncertain, set transaction_id to null and lower confidence."
    )

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=900,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "text", "text": f"Transcript:\n{transcript_text}"},
                ],
            }
        ],
    )
    payload = _extract_json_block(_extract_response_text(response))
    if not isinstance(payload, dict):
        return None
    payload["parser"] = "claude"
    return payload


def _download_recording_bytes(recording_url):
    if not recording_url:
        return None, "", "Recording URL missing."

    target_url = recording_url.strip()
    if not target_url.lower().endswith((".mp3", ".wav")):
        target_url = f"{target_url}.mp3"

    request = Request(target_url)
    account_sid = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
    auth_token = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
    if account_sid and auth_token:
        token = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("utf-8")
        request.add_header("Authorization", f"Basic {token}")
    request.add_header("User-Agent", "MaverickVoiceNotes/1.0")

    try:
        with urlopen(request, timeout=25) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "audio/mpeg")
            return data, content_type, ""
    except URLError as exc:
        return None, "", f"Unable to download recording: {exc}"


def _transcribe_with_claude_audio(recording_url):
    """Attempt direct audio transcription using Claude audio input."""
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key or Anthropic is None:
        return "", "Claude unavailable (missing API key)."

    audio_bytes, content_type, download_error = _download_recording_bytes(recording_url)
    if not audio_bytes:
        return "", download_error or "Recording download failed."

    media_type = "audio/mpeg"
    if "wav" in (content_type or "").lower():
        media_type = "audio/wav"

    model = (os.getenv("VOICE_NOTE_CLAUDE_MODEL") or "claude-sonnet-4-20250514").strip()
    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1200,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Transcribe this voice note exactly. Return plain transcript text only. "
                                "Do not return JSON."
                            ),
                        },
                        {
                            "type": "input_audio",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(audio_bytes).decode("utf-8"),
                            },
                        },
                    ],
                }
            ],
        )
        transcript = _extract_response_text(response)
        if transcript:
            return transcript.strip(), ""
        return "", "Claude returned an empty transcript."
    except Exception as exc:  # pragma: no cover - external API
        return "", f"Claude transcription failed: {str(exc)[:300]}"


def _sanitize_payload(raw_payload, transcript_text):
    payload = dict(raw_payload or {})
    transaction_id = _safe_int(payload.get("transaction_id"))
    note_type = _normalize_note_type(payload.get("note_type"))
    content = str(payload.get("content") or "").strip()
    if not content:
        content = (transcript_text or "").strip()[:1200]
    complete_tasks = _sanitize_list(payload.get("complete_tasks"))
    create_tasks = _sanitize_list(payload.get("create_tasks"))
    confidence = _safe_int(payload.get("confidence"))
    if confidence is None:
        confidence = 65 if payload.get("parser") == "claude" else 55
    confidence = max(0, min(confidence, 100))

    if not transaction_id:
        inferred_id = parse_transaction_id_from_transcript(transcript_text)
        if inferred_id:
            transaction_id = inferred_id
            confidence = min(100, confidence + 8)
    if not complete_tasks and "loan approved" in (transcript_text or "").lower():
        complete_tasks = ["Get loan approval"]
    if not create_tasks and "cd ready" in (transcript_text or "").lower():
        create_tasks = ["Review CD when received"]

    return {
        "transaction_id": transaction_id,
        "note_type": note_type,
        "content": content[:1400],
        "complete_tasks": complete_tasks,
        "create_tasks": create_tasks,
        "confidence": confidence,
        "parser": payload.get("parser") or "heuristic",
    }


def _find_transaction(transaction_id):
    if not transaction_id:
        return None
    rows = execute_query(
        """
        SELECT id, property_address, status
        FROM transactions
        WHERE id = %s
        LIMIT 1
        """,
        (transaction_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def _create_review_task(transaction_id, transcript_text, confidence, note_type):
    description = "Review voice note transcription before applying updates"
    existing = execute_query(
        """
        SELECT id
        FROM tasks
        WHERE transaction_id = %s
          AND completed = FALSE
          AND COALESCE(status, 'pending') <> 'completed'
          AND LOWER(task_description) = LOWER(%s)
        ORDER BY id DESC
        LIMIT 1
        """,
        (transaction_id, description),
        fetch=True,
    ) or []
    if existing:
        return existing[0]["id"]

    note = (
        f"Auto-flagged from voice note ({note_type}). "
        f"Confidence={confidence}%. Transcript excerpt: {(transcript_text or '')[:450]}"
    )
    rows = execute_query(
        """
        INSERT INTO tasks (
            transaction_id, task_description, task_category, due_date,
            priority, status, completed, display_order, notes, created_at
        )
        VALUES (%s, %s, 'coordination', %s, 'high', 'pending', FALSE, 64, %s, CURRENT_TIMESTAMP)
        RETURNING id
        """,
        (transaction_id, description, date.today(), note),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def _complete_task_fragments(transaction_id, task_fragments, transcript_text):
    completed_ids = []
    used_fragments = []
    for fragment in task_fragments:
        fragment_text = (fragment or "").strip()
        if len(fragment_text) < 3:
            continue
        rows = execute_query(
            """
            SELECT id, task_description
            FROM tasks
            WHERE transaction_id = %s
              AND completed = FALSE
              AND COALESCE(status, 'pending') <> 'completed'
              AND LOWER(task_description) LIKE LOWER(%s)
            ORDER BY due_date ASC NULLS LAST, id ASC
            LIMIT 1
            """,
            (transaction_id, f"%{fragment_text}%"),
            fetch=True,
        ) or []
        if not rows:
            continue
        task_id = rows[0]["id"]
        if task_id in completed_ids:
            continue
        note_entry = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
            f"[Voice note auto-complete] Matched fragment '{fragment_text}'. "
            f"Transcript: {(transcript_text or '')[:250]}"
        )
        execute_query(
            """
            UPDATE tasks
            SET completed = TRUE,
                status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                completed_by = 'voice-note-auto',
                notes = CASE
                    WHEN COALESCE(notes, '') = '' THEN %s
                    ELSE notes || E'\n' || %s
                END
            WHERE id = %s
            """,
            (note_entry, note_entry, task_id),
        )
        completed_ids.append(task_id)
        used_fragments.append(fragment_text)
    return completed_ids, used_fragments


def _create_tasks(transaction_id, task_descriptions, transcript_text):
    created_ids = []
    created_descriptions = []
    for description in task_descriptions:
        task_text = (description or "").strip()
        if len(task_text) < 4:
            continue
        existing = execute_query(
            """
            SELECT id
            FROM tasks
            WHERE transaction_id = %s
              AND LOWER(task_description) = LOWER(%s)
              AND completed = FALSE
              AND COALESCE(status, 'pending') <> 'completed'
            ORDER BY id DESC
            LIMIT 1
            """,
            (transaction_id, task_text),
            fetch=True,
        ) or []
        if existing:
            continue

        note = (
            f"Auto-created from voice note transcript at {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
            f"Transcript excerpt: {(transcript_text or '')[:300]}"
        )
        rows = execute_query(
            """
            INSERT INTO tasks (
                transaction_id, task_description, task_category, due_date,
                priority, status, completed, display_order, notes, created_at
            )
            VALUES (%s, %s, 'coordination', %s, 'medium', 'pending', FALSE, 63, %s, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (transaction_id, task_text[:300], date.today() + timedelta(days=1), note),
            fetch=True,
        ) or []
        if rows:
            created_ids.append(rows[0]["id"])
            created_descriptions.append(task_text[:300])
    return created_ids, created_descriptions


def _insert_communication(transaction_id, from_phone, parsed_payload, actions_taken, review_required):
    note_type = (parsed_payload.get("note_type") or DEFAULT_VOICE_NOTE_TYPE).replace("_", " ").title()
    content = (parsed_payload.get("content") or "").strip()
    summary = f"Voice note ({note_type})"
    if content:
        summary = f"{summary}: {content[:180]}"

    action_bits = []
    if actions_taken.get("completed_task_ids"):
        action_bits.append(f"completed={len(actions_taken['completed_task_ids'])}")
    if actions_taken.get("created_task_ids"):
        action_bits.append(f"created={len(actions_taken['created_task_ids'])}")
    if actions_taken.get("review_task_id"):
        action_bits.append(f"review_task={actions_taken['review_task_id']}")

    outcome = (
        f"from={from_phone or 'unknown'} "
        f"confidence={parsed_payload.get('confidence', 0)}% "
        f"review_required={review_required} "
        f"{' '.join(action_bits)}"
    ).strip()

    rows = execute_query(
        """
        INSERT INTO communications (
            transaction_id, communication_type, contact_party, contact_name,
            summary, outcome, logged_by
        )
        VALUES (%s, 'voice_note', 'margaret', %s, %s, %s, 'system')
        RETURNING id
        """,
        (
            transaction_id,
            from_phone or "Margaret",
            summary[:500],
            outcome[:2000],
        ),
        fetch=True,
    ) or []
    return rows[0]["id"] if rows else None


def _notify_margaret(message_text):
    margaret_phone = normalize_phone(os.getenv("MARGARET_PHONE") or "")
    if not margaret_phone:
        return None
    return send_sms(margaret_phone, (message_text or "")[:1500])


def _update_voice_note_row(
    voice_note_id,
    *,
    status=None,
    review_required=None,
    transaction_id=None,
    communication_id=None,
    transcription_text=None,
    transcription_source=None,
    parse_payload=None,
    confidence_score=None,
    note_type=None,
    actions_taken=None,
    error_message=None,
    processed=False,
):
    execute_query(
        """
        UPDATE voice_notes
        SET status = COALESCE(%s, status),
            review_required = COALESCE(%s, review_required),
            transaction_id = COALESCE(%s, transaction_id),
            communication_id = COALESCE(%s, communication_id),
            transcription_text = COALESCE(%s, transcription_text),
            transcription_source = COALESCE(%s, transcription_source),
            parse_payload = COALESCE(%s::jsonb, parse_payload),
            confidence_score = COALESCE(%s, confidence_score),
            note_type = COALESCE(%s, note_type),
            actions_taken = COALESCE(%s::jsonb, actions_taken),
            error_message = COALESCE(%s, error_message),
            updated_at = CURRENT_TIMESTAMP,
            processed_at = CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE processed_at END
        WHERE id = %s
        """,
        (
            status,
            review_required,
            transaction_id,
            communication_id,
            transcription_text,
            transcription_source,
            json.dumps(parse_payload) if parse_payload is not None else None,
            confidence_score,
            note_type,
            json.dumps(actions_taken) if actions_taken is not None else None,
            error_message,
            bool(processed),
            voice_note_id,
        ),
    )


def register_voice_note_capture(
    call_sid,
    recording_sid,
    recording_url,
    from_phone,
    recording_duration_seconds=0,
    transcription_text="",
    transcription_source="",
):
    """Create/update voice-note capture row from Twilio recording callback."""
    ensure_voice_note_tables()
    duration = _safe_int(recording_duration_seconds) or 0
    source = (transcription_source or "").strip().lower() or None
    transcript = (transcription_text or "").strip() or None
    base_status = "transcribed" if transcript else ("awaiting_transcription" if _voice_note_transcription_mode() == "twilio" else "received")

    if recording_sid:
        rows = execute_query(
            """
            INSERT INTO voice_notes (
                call_sid, recording_sid, from_phone, recording_url, recording_duration_seconds,
                transcription_text, transcription_source, status, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (recording_sid)
            DO UPDATE SET
                call_sid = COALESCE(EXCLUDED.call_sid, voice_notes.call_sid),
                from_phone = COALESCE(EXCLUDED.from_phone, voice_notes.from_phone),
                recording_url = COALESCE(EXCLUDED.recording_url, voice_notes.recording_url),
                recording_duration_seconds = GREATEST(
                    COALESCE(voice_notes.recording_duration_seconds, 0),
                    COALESCE(EXCLUDED.recording_duration_seconds, 0)
                ),
                transcription_text = COALESCE(EXCLUDED.transcription_text, voice_notes.transcription_text),
                transcription_source = COALESCE(EXCLUDED.transcription_source, voice_notes.transcription_source),
                status = CASE
                    WHEN voice_notes.status IN ('executed', 'review_required') THEN voice_notes.status
                    WHEN EXCLUDED.transcription_text IS NOT NULL AND EXCLUDED.transcription_text <> '' THEN 'transcribed'
                    ELSE COALESCE(voice_notes.status, EXCLUDED.status)
                END,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, status
            """,
            (
                call_sid or None,
                recording_sid,
                normalize_phone(from_phone),
                recording_url or None,
                duration,
                transcript,
                source,
                base_status,
            ),
            fetch=True,
        ) or []
        return rows[0] if rows else None

    rows = execute_query(
        """
        INSERT INTO voice_notes (
            call_sid, from_phone, recording_url, recording_duration_seconds,
            transcription_text, transcription_source, status, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        RETURNING id, status
        """,
        (
            call_sid or None,
            normalize_phone(from_phone),
            recording_url or None,
            duration,
            transcript,
            source,
            base_status,
        ),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def queue_voice_note_processing(voice_note_id, transcription_text=None, transcription_source=None):
    """Launch background processing for one voice note id."""
    if not voice_note_id:
        return False
    with _VOICE_NOTE_PROCESSING_LOCK:
        if voice_note_id in _VOICE_NOTE_PROCESSING_ACTIVE:
            return False
        _VOICE_NOTE_PROCESSING_ACTIVE.add(voice_note_id)
    thread = threading.Thread(
        target=_process_voice_note_worker,
        args=(voice_note_id, transcription_text, transcription_source),
        daemon=True,
    )
    thread.start()
    return True


def _process_voice_note_worker(voice_note_id, transcription_text=None, transcription_source=None):
    try:
        _process_voice_note(voice_note_id, transcription_text=transcription_text, transcription_source=transcription_source)
    finally:
        with _VOICE_NOTE_PROCESSING_LOCK:
            _VOICE_NOTE_PROCESSING_ACTIVE.discard(voice_note_id)


def _process_voice_note(voice_note_id, transcription_text=None, transcription_source=None):
    ensure_voice_note_tables()
    rows = execute_query(
        """
        SELECT id, call_sid, recording_sid, from_phone, recording_url, recording_duration_seconds,
               transcription_text, transcription_source, status
        FROM voice_notes
        WHERE id = %s
        LIMIT 1
        """,
        (voice_note_id,),
        fetch=True,
    ) or []
    if not rows:
        return
    row = rows[0]
    _update_voice_note_row(voice_note_id, status="processing")

    transcript = (transcription_text or row.get("transcription_text") or "").strip()
    source = (transcription_source or row.get("transcription_source") or "").strip().lower() or None

    if not transcript and _voice_note_transcription_mode() == "claude":
        transcript, err = _transcribe_with_claude_audio(row.get("recording_url"))
        if transcript:
            source = "claude"
        else:
            _update_voice_note_row(
                voice_note_id,
                status="review_required",
                review_required=True,
                error_message=err or "Transcription unavailable.",
                processed=True,
            )
            _notify_margaret(
                "Voice note received but transcription failed. "
                f"Recording SID {row.get('recording_sid') or voice_note_id}. "
                f"{(err or '')[:240]}"
            )
            return

    if not transcript:
        _update_voice_note_row(voice_note_id, status="awaiting_transcription")
        return

    parsed = _parse_with_claude(transcript) or _heuristic_parse_transcript(transcript)
    payload = _sanitize_payload(parsed, transcript)
    transaction_id = payload.get("transaction_id")
    confidence = int(payload.get("confidence") or 0)
    review_required = confidence < VOICE_NOTE_REVIEW_THRESHOLD
    note_type = payload.get("note_type") or DEFAULT_VOICE_NOTE_TYPE

    transaction = _find_transaction(transaction_id)
    if not transaction:
        _update_voice_note_row(
            voice_note_id,
            status="review_required",
            review_required=True,
            transcription_text=transcript,
            transcription_source=source or "unknown",
            parse_payload=payload,
            confidence_score=confidence,
            note_type=note_type,
            transaction_id=None,
            error_message="Could not resolve transaction id from transcript.",
            processed=True,
        )
        _notify_margaret(
            "Voice note transcription received but transaction ID could not be resolved. "
            f"Transcript: {transcript[:260]}"
        )
        return

    actions_taken = {
        "auto_executed": False,
        "completed_task_ids": [],
        "created_task_ids": [],
    }
    if review_required:
        review_task_id = _create_review_task(transaction["id"], transcript, confidence, note_type)
        actions_taken["review_task_id"] = review_task_id
    else:
        completed_ids, completed_fragments = _complete_task_fragments(
            transaction_id=transaction["id"],
            task_fragments=payload.get("complete_tasks") or [],
            transcript_text=transcript,
        )
        created_ids, created_descriptions = _create_tasks(
            transaction_id=transaction["id"],
            task_descriptions=payload.get("create_tasks") or [],
            transcript_text=transcript,
        )
        actions_taken.update(
            {
                "auto_executed": True,
                "completed_task_ids": completed_ids,
                "created_task_ids": created_ids,
                "completed_fragments": completed_fragments,
                "created_descriptions": created_descriptions,
            }
        )

    communication_id = _insert_communication(
        transaction_id=transaction["id"],
        from_phone=row.get("from_phone") or "",
        parsed_payload=payload,
        actions_taken=actions_taken,
        review_required=review_required,
    )

    final_status = "review_required" if review_required else "executed"
    _update_voice_note_row(
        voice_note_id,
        status=final_status,
        review_required=review_required,
        transaction_id=transaction["id"],
        communication_id=communication_id,
        transcription_text=transcript,
        transcription_source=source or "unknown",
        parse_payload=payload,
        confidence_score=confidence,
        note_type=note_type,
        actions_taken=actions_taken,
        error_message=None,
        processed=True,
    )

    if review_required:
        _notify_margaret(
            f"Voice note for transaction #{transaction['id']} needs review "
            f"({confidence}% confidence)."
        )
    else:
        _notify_margaret(
            f"Voice note processed for transaction #{transaction['id']}: "
            f"completed {len(actions_taken['completed_task_ids'])} task(s), "
            f"created {len(actions_taken['created_task_ids'])} task(s)."
        )


def handle_twilio_transcription_callback(recording_sid, transcription_text, transcription_status="completed"):
    """
    Store Twilio transcription callback and queue processing.
    Returns dict with voice_note_id when matched.
    """
    ensure_voice_note_tables()
    sid = (recording_sid or "").strip()
    if not sid:
        return {"success": False, "error": "missing_recording_sid"}

    rows = execute_query(
        """
        SELECT id, status, communication_id
        FROM voice_notes
        WHERE recording_sid = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (sid,),
        fetch=True,
    ) or []
    if not rows:
        return {"success": False, "error": "recording_not_found"}

    voice_note_id = rows[0]["id"]
    current_status = (rows[0].get("status") or "").strip().lower()
    if current_status in {"executed", "review_required"} and rows[0].get("communication_id"):
        return {"success": True, "voice_note_id": voice_note_id, "queued": False, "ignored": "already_processed"}

    status_text = (transcription_status or "").strip().lower()
    transcript = (transcription_text or "").strip()

    if status_text in {"failed", "error"} or (not transcript and status_text and status_text != "completed"):
        _update_voice_note_row(
            voice_note_id,
            status="review_required",
            review_required=True,
            transcription_text=transcript or None,
            transcription_source="twilio",
            error_message=f"Twilio transcription status: {status_text or 'unknown'}",
            processed=True,
        )
        _notify_margaret(
            f"Voice note transcription failed for recording {sid}. "
            "Please review manually in Maverick."
        )
        return {"success": True, "voice_note_id": voice_note_id, "queued": False}

    if transcript:
        _update_voice_note_row(
            voice_note_id,
            status="transcribed",
            transcription_text=transcript,
            transcription_source="twilio",
            error_message=None,
        )
        queued = queue_voice_note_processing(
            voice_note_id=voice_note_id,
            transcription_text=transcript,
            transcription_source="twilio",
        )
        return {"success": True, "voice_note_id": voice_note_id, "queued": queued}

    _update_voice_note_row(voice_note_id, status="awaiting_transcription")
    return {"success": True, "voice_note_id": voice_note_id, "queued": False}


def fetch_voice_note_audio_payload(voice_note_id):
    """Download audio bytes for one stored voice note."""
    ensure_voice_note_tables()
    rows = execute_query(
        """
        SELECT id, recording_sid, recording_url
        FROM voice_notes
        WHERE id = %s
        LIMIT 1
        """,
        (voice_note_id,),
        fetch=True,
    ) or []
    if not rows:
        return {"success": False, "error": "Voice note not found."}
    row = rows[0]
    audio_bytes, content_type, err = _download_recording_bytes(row.get("recording_url"))
    if not audio_bytes:
        return {"success": False, "error": err or "Unable to download voice note audio."}

    recording_sid = (row.get("recording_sid") or f"voice-note-{voice_note_id}").strip()
    filename = f"{recording_sid}.mp3"
    return {
        "success": True,
        "content_type": (content_type or "audio/mpeg").split(";")[0].strip() or "audio/mpeg",
        "filename": filename,
        "data": audio_bytes,
    }

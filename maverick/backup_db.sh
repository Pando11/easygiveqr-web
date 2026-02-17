#!/usr/bin/env bash
set -Eeuo pipefail

# Maverick nightly database backup
# Suggested cron: 0 2 * * * /workspace/maverick/backup_db.sh

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

send_heidi_sms() {
  local body="$1"
  if [[ -z "${TWILIO_ACCOUNT_SID:-}" || -z "${TWILIO_AUTH_TOKEN:-}" || -z "${TWILIO_PHONE_NUMBER:-}" || -z "${HEIDI_PHONE:-}" ]]; then
    log "Skipping Heidi SMS (Twilio credentials or HEIDI_PHONE missing)."
    return 0
  fi

  curl -sS -X POST "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json" \
    --data-urlencode "Body=${body}" \
    --data-urlencode "From=${TWILIO_PHONE_NUMBER}" \
    --data-urlencode "To=${HEIDI_PHONE}" \
    -u "${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}" >/dev/null || true
}

cleanup() {
  if [[ -n "${BACKUP_FILE:-}" && -f "${BACKUP_FILE}" ]]; then
    rm -f "${BACKUP_FILE}"
  fi
}

on_error() {
  local line_no="$1"
  log "Backup failed at line ${line_no}."
  send_heidi_sms "Maverick backup FAILED on $(hostname) at $(date '+%Y-%m-%d %H:%M:%S')."
}

trap cleanup EXIT
trap 'on_error $LINENO' ERR

if [[ -z "${DATABASE_URL:-}" ]]; then
  log "DATABASE_URL is not set."
  exit 1
fi

if [[ -z "${AWS_S3_BUCKET_BACKUPS:-}" ]]; then
  log "AWS_S3_BUCKET_BACKUPS is not set."
  exit 1
fi

TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_FILE="/tmp/maverick_db_${TIMESTAMP}.sql"
BACKUP_KEY="database/maverick_db_${TIMESTAMP}.sql"

log "Starting PostgreSQL dump."
pg_dump "${DATABASE_URL}" --no-owner --no-privileges > "${BACKUP_FILE}"

log "Uploading backup to s3://${AWS_S3_BUCKET_BACKUPS}/${BACKUP_KEY}"
aws s3 cp "${BACKUP_FILE}" "s3://${AWS_S3_BUCKET_BACKUPS}/${BACKUP_KEY}"

log "Applying retention policy: keep latest 30 backups."
mapfile -t BACKUP_KEYS < <(
  aws s3 ls "s3://${AWS_S3_BUCKET_BACKUPS}/database/" \
    | awk '{print $4}' \
    | rg '^maverick_db_.*\.sql$' \
    | sort -r
)

if (( ${#BACKUP_KEYS[@]} > 30 )); then
  for ((i=30; i<${#BACKUP_KEYS[@]}; i++)); do
    old_key="${BACKUP_KEYS[$i]}"
    [[ -z "${old_key}" ]] && continue
    aws s3 rm "s3://${AWS_S3_BUCKET_BACKUPS}/database/${old_key}"
    log "Deleted old backup: ${old_key}"
  done
fi

log "Backup completed successfully."
send_heidi_sms "Maverick backup success on $(hostname) at $(date '+%Y-%m-%d %H:%M:%S')."

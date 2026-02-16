#!/usr/bin/env bash
set -euo pipefail

# Maverick Database Backup Script
# Intended for daily scheduled execution

send_backup_notification() {
  local body="$1"
  if [[ -n "${TWILIO_ACCOUNT_SID:-}" && -n "${TWILIO_AUTH_TOKEN:-}" && -n "${TWILIO_PHONE_NUMBER:-}" && -n "${HEIDI_PHONE:-}" ]]; then
    curl -sS -X POST "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json" \
      --data-urlencode "Body=${body}" \
      --data-urlencode "From=${TWILIO_PHONE_NUMBER}" \
      --data-urlencode "To=${HEIDI_PHONE}" \
      -u "${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}" >/dev/null || true
  else
    echo "Twilio backup notification skipped: missing credentials/phone variables."
  fi
}

on_exit() {
  local exit_code="$1"
  if [[ "${exit_code}" -eq 0 ]]; then
    send_backup_notification "Maverick backup completed successfully at $(date)"
  else
    send_backup_notification "Maverick backup FAILED at $(date)"
  fi
}
trap 'on_exit $?' EXIT

echo "Starting Maverick backup..."

DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="/tmp/maverick_db_${TIMESTAMP}.sql"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set."
  exit 1
fi

if [[ -z "${AWS_S3_BUCKET_BACKUPS:-}" ]]; then
  echo "AWS_S3_BUCKET_BACKUPS is not set."
  exit 1
fi

echo "Backing up database..."
pg_dump "${DATABASE_URL}" > "${BACKUP_FILE}"

echo "Uploading to S3..."
aws s3 cp "${BACKUP_FILE}" "s3://${AWS_S3_BUCKET_BACKUPS}/database/${DATE}.sql"

echo "Cleaning local backup..."
rm -f "${BACKUP_FILE}"

echo "Cleaning backups older than 30 days..."
aws s3 ls "s3://${AWS_S3_BUCKET_BACKUPS}/database/" | while read -r line; do
  create_date=$(echo "${line}" | awk '{print $1" "$2}')
  create_epoch=$(date -d "${create_date}" +%s || true)
  cutoff_epoch=$(date --date="30 days ago" +%s)
  if [[ -n "${create_epoch}" && "${create_epoch}" -lt "${cutoff_epoch}" ]]; then
    file_name=$(echo "${line}" | awk '{print $4}')
    if [[ -n "${file_name}" ]]; then
      aws s3 rm "s3://${AWS_S3_BUCKET_BACKUPS}/database/${file_name}"
      echo "Deleted old backup: ${file_name}"
    fi
  fi
done

echo "Backup complete."

#!/usr/bin/env bash
set -euo pipefail

# Maverick Database Backup Script
# Intended for daily scheduled execution

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

# Railway Cron Jobs for Maverick

Use these schedules and commands in Railway Cron.

## Daily Reminders
- Schedule: `0 8 * * *`
- Command: `python send_reminders.py`

## Closing Protocol Morning
- Schedule: `0 8 * * *`
- Command: `python closing_protocol.py`

## Closing Protocol Midday
- Schedule: `0 10 * * *`
- Command: `python closing_protocol.py`

## Closing Protocol Evening
- Schedule: `0 17 * * *`
- Command: `python closing_protocol.py`

## Problem Detection
- Schedule: `0 */6 * * *`
- Command: `python check_problems.py`

## Database Backup
- Schedule: `0 2 * * *`
- Command: `bash backup_db.sh`

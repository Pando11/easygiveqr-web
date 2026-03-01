# Railway Cron Jobs for Maverick

Use these schedules and commands in Railway Cron.

## Daily Reminders
- Schedule: `0 8 * * *`
- Command: `python send_reminders.py`
- Includes:
  - 10/7/3/1 day deadline reminder SMS
  - critical/overdue summary alerts
  - legacy proactive nudge engine only when `ENABLE_LEGACY_DEADLINE_NUDGES=true`

## Intelligent Deadline Nudges
- Schedule: `0 7 * * *`
- Command: `cd maverick && python3 automation/intelligent_nudges.py`
- Includes:
  - proactive deadline checks by nudge type + configurable timing
  - duplicate prevention using `nudge_log`
  - auto follow-up task creation for unresolved responses

## Predictive Alerts
- Schedule: `0 6 * * *`
- Command: `python predictive_alerts.py`

## Heads Up Monitor
- Schedule: `15 6 * * *`
- Command: `python heads_up_monitor.py`

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
- Command: `cd maverick && python3 automation/problem_detector.py`

## Automated Agent Status Updates
- Schedule: `0 * * * *`
- Command: `cd maverick && python3 automation/agent_status_updates.py`
- Includes:
  - schedule-aware send (Monday 8am OR Friday 5pm from TC settings)
  - one-send-per-week guard for scheduled runs
  - per-transaction agent update emails with progress + urgent items

## Dynamic Closing Checklists
- Schedule: `0 * * * *`
- Command: `cd maverick && python3 automation/closing_checklists.py`
- Includes:
  - generates checklist exactly 3 days before closing for active transactions
  - prepares PDF + interactive checklist recipient links
  - auto-sends with disclaimer after 24 hours if Margaret has not approved

## Auto Task Completion
- Schedule: `*/15 * * * *`
- Command: `cd maverick && python3 automation/task_auto_completion.py`
- Includes:
  - rule-based task completion checks
  - confidence scoring + review flags below 80%
  - high-stakes task exclusion (never auto-complete)

## Database Backup
- Schedule: `0 2 * * *`
- Command: `bash backup_db.sh`

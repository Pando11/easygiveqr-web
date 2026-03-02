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

## Intelligent Daily Plan (pre-briefing)
- Schedule: `0 7 * * *`
- Command: `cd maverick && python3 automation/generate_daily_plan.py`
- Includes:
  - AI categorization + time-block generation
  - adaptive delegate suggestions
  - SMS/email daily plan delivery
  - Google Calendar block sync

## Daily Plan Estimate Learning (weekly)
- Schedule: `0 6 * * 1`
- Command: `cd maverick && python3 automation/generate_daily_plan.py --update-estimates --estimates-only --estimate-days 30`
- Includes:
  - refreshes `task_time_estimates` from `task_completion_times`
  - applies 10% buffer to learned averages for planning realism

## Intelligent Morning Briefing
- Schedule: `30 7 * * *`
- Command: `cd maverick && python3 automation/morning_briefing.py --mode morning`
- Includes:
  - AI-prioritized morning action board (SMS + detailed email)
  - pattern highlights + batching suggestions
  - interactive `/tc/morning-briefing` checklist population

## Evening Recap
- Schedule: `0 14 * * *`
- Command: `cd maverick && python3 automation/morning_briefing.py --mode evening`
- Includes:
  - 2 PM progress summary (done vs pending/deferred)
  - rollover-to-tomorrow view
  - completion celebration highlights

## Post-Close Review + Referral Follow-up
- Schedule: `15 9 * * *`
- Command: `cd maverick && python3 automation/review_referral_followup.py --days-after-close 7 --limit 200`
- Includes:
  - sends "How did we do?" email 7 days after closing
  - includes direct Google review link + tracked referral offer link
  - tracks internal review responses, star ratings, referral clicks, and conversions

## Database Backup
- Schedule: `0 2 * * *`
- Command: `bash backup_db.sh`

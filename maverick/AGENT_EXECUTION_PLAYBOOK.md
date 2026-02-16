# Maverick Agent Execution Playbook

Use this document to coordinate engineers/agents and finish the remaining MVP build.

## 1) Current status snapshot

Implemented already:
- Agent upload form + `/upload`
- Core schema and helper modules
- Stripe payment page + processing route
- Stripe webhook route (`/stripe/webhook`)
- Reminder / closing / problem scripts
- Stripe minions (payment links, dunning, reconciliation)
- Launch checks and Stripe.dev bootstrap tooling

Not fully implemented yet (MVP gaps):
- Full Margaret review queue and approval workflow
- Deadline auto-generation from contract/effective date
- 30-task auto-generation and richer task management UI
- Full document center (list/view/upload/distribute by transaction)
- Communication log UX for calls/emails/texts
- Full transaction detail dashboard UX (beyond current stubs)
- End-to-end automated tests (API + UI smoke)

---

## 2) Agent onboarding (all agents)

From repo root:

```bash
make stripe-dev-up
```

If this fails, fill `maverick/.env` first using:
- `maverick/.env.example`
- `maverick/STRIPE_DEV_SETUP.md`

Start app:

```bash
python maverick/app.py
```

---

## 3) Workstream assignments (parallel)

## Agent A - Review + Approval workflow (P0)

Goal: move uploaded contracts from `NEEDS_MARGARET_REVIEW` to `ACTIVE` using a real review UI.

Build:
1. Review queue page:
   - `GET /tc/review-queue`
   - filters by status and created date
2. Review detail page:
   - `GET /tc/transaction/<id>/review`
   - `POST /tc/transaction/<id>/approve`
3. Approval save fields:
   - effective date, closing date
   - key parties (buyer/seller/lender/title)
4. Status transition:
   - `NEEDS_MARGARET_REVIEW` -> `ACTIVE`
5. On approve, trigger:
   - deadline generation
   - task generation
   - timeline SMS
   - upfront payment link SMS

Acceptance criteria:
- Upload a contract, approve in UI, and status becomes `ACTIVE`.
- Agent receives timeline + payment SMS.

---

## Agent B - Deadline + Task engine (P0)

Goal: generate deadlines and tasks consistently after approval.

Build:
1. `utils/deadline_engine.py`
   - generate 10/7/3/1 reminder-ready deadlines from effective date and contract fields
2. `utils/task_engine.py`
   - generate baseline 30 task set with due dates, categories, priorities
3. Idempotency:
   - re-approving should not duplicate existing deadlines/tasks
4. Admin recalc route:
   - `POST /tc/transaction/<id>/recalculate-plan`

Acceptance criteria:
- Approved transaction has deadlines + tasks populated.
- Recalculate does not create duplicates.

---

## Agent C - Documents + communications UX (P0)

Goal: complete day-to-day coordination interface.

Build:
1. Transaction document center:
   - list docs by type/date
   - upload additional docs to S3
   - view/download via presigned URL
2. Communication logging UI:
   - add call/email/text entries
   - show latest entries on transaction page
3. Add `/tc/transaction/<id>` upgrades:
   - tabs: Overview, Tasks, Documents, Communications, Payments

Acceptance criteria:
- Can upload doc, then view/download from transaction page.
- Can log communication and see it immediately.

---

## Agent D - QA + release hardening (P0)

Goal: prove reliability and prevent regressions.

Build:
1. API smoke suite (pytest):
   - upload validation
   - payment route validation
   - webhook signature handling
2. Scripted end-to-end test:
   - upload -> approve -> pay -> complete
3. Add pre-release checklist markdown:
   - `maverick/RELEASE_CHECKLIST.md`
4. CI command bundle doc:
   - compile, smoke tests, launch checks, minion dry-run

Acceptance criteria:
- Repeatable local/CI test run with pass/fail output.

---

## 4) Suggested branch strategy

Each agent uses feature branches from `cursor/new-project-setup-b37f`:

- `feature/maverick-review-approval`
- `feature/maverick-deadline-task-engine`
- `feature/maverick-docs-communications`
- `feature/maverick-qa-hardening`

Commit style:
- `feat: ...`
- `fix: ...`
- `test: ...`
- `docs: ...`

---

## 5) Integration order

1. Merge Agent B engine work first.
2. Merge Agent A review/approval flow (depends on engines).
3. Merge Agent C UX enhancements.
4. Merge Agent D tests + release checklist.
5. Run:
   - `python maverick/run_launch_checks.py`
   - `python maverick/run_stripe_minions.py --all --dry-run`
   - full manual QA scenario

---

## 6) Definition of done (team-wide)

A task is done only if all are true:
- feature works end-to-end locally
- no syntax errors (`python -m compileall maverick`)
- launch checks run
- docs updated for any new env/routes
- changes committed and pushed

---

## 7) Daily standup template

Each agent posts:
1. Completed yesterday
2. In progress today
3. Blockers (with owner needed)
4. PR/commit link


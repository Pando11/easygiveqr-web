# EasyGiveQR Web

EasyGiveQR Web is a Next.js + TypeScript project for donation checkout, church
onboarding, and operational admin tooling.

## Start a new project in this repo

### Prerequisites

- Node.js 20+
- npm 10+
- Supabase project
- Stripe account (test keys are enough to start)
- SendGrid account (or stub values for local-only testing)

### Quick start

```bash
npm run setup
```

The setup script will:

1. Install dependencies (if needed)
2. Create `.env.local` from `.env.example` if missing

Then fill in `.env.local` and run:

```bash
npm run dev
```

Open <http://localhost:3000>.

## Environment variables

Copy `.env.example` to `.env.local` and populate values.

### Required

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `SENDGRID_API_KEY`
- `SENDGRID_FROM_EMAIL`
- `ADMIN_SECRET`
- `CRON_SECRET`
- `NEXT_PUBLIC_SITE_URL`
- `NODE_ENV`

### Optional

- `SITE_URL` (preferred canonical URL in production)
- `SENDGRID_REPLY_TO_EMAIL`
- `STRIPE_PUBLISHABLE_KEY`
- `DONATIONS_PAUSED`
- `ALLOW_DONATIONS_WHEN_INACTIVE`
- `SENTRY_DSN`
- `VERCEL_ENV`

## Scripts

- `npm run setup` - install dependencies and create `.env.local`
- `npm run dev` - run local development server
- `npm run build` - production build
- `npm run start` - run production server
- `npm run lint` - ESLint checks
- `npm run typecheck` - TypeScript checks
- `npm run check` - lint + typecheck

## Project structure

```text
src/
  app/              # Next.js App Router pages and API routes
  lib/              # Shared business logic and utilities
scripts/            # Maintenance and helper scripts
supabase/migrations # Database schema migrations
```

## First milestone checklist

- [ ] Configure `.env.local`
- [ ] Run `npm run check`
- [ ] Hit `GET /api/health` and confirm `"ok": true`
- [ ] Validate a local donation flow from `/donate?church_id=EGQR-123`
- [ ] Add your first feature branch change

## Additional docs

- `DEPLOYMENT_GUIDE.md`
- `VERCEL_DEPLOYMENT.md`
- `STRIPE_SETUP.md`
- `OPS_RUNBOOK.md`

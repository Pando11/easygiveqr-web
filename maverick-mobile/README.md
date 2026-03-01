# Maverick Mobile (React Native / Expo)

This is the new, separate mobile codebase for Maverick TC.

## MVP features included

- JWT login for mobile (`POST /api/mobile/login`)
- Dashboard view (`GET /api/mobile/dashboard`)
- Daily checklist view (`GET /api/mobile/daily-checklist`)
- Task completion (`POST /api/mobile/task/<task_id>/complete`)
- Document viewing (`GET /api/mobile/transaction/<transaction_id>/documents`)
- Call workflow support
  - Dial from app (`tel:` links from checklist payload)
  - Mark call complete (`POST /api/mobile/call/<deadline_id>/complete`)
- Communication logging
  - List (`GET /api/mobile/transaction/<transaction_id>/communications`)
  - Create (`POST /api/mobile/transaction/<transaction_id>/communications`)

## Local development

```bash
cd /workspace/maverick-mobile
npm install
npm run start
```

Open in:
- Expo Go on iOS/Android
- iOS simulator (`npm run ios`, macOS only)
- Android emulator (`npm run android`)

## Configure API base URL

In the app login screen, set **API Base URL** to your deployed backend URL.

Example:

```
https://maverick-tc.up.railway.app
```

## Deploy backend API routes (Railway)

From the backend project directory:

```bash
cd /workspace/maverick
railway up
```

or if Railway CLI is unavailable:

```bash
cd /workspace/maverick
npx @railway/cli up
```

## App Store / Google Play submission checklist

Submission itself requires account access and signing credentials.

1. Create Apple Developer + Google Play Console app records
2. Configure app identifiers/package names and app icons/splash
3. Build signed artifacts with Expo EAS:
   - `eas build -p ios --profile production`
   - `eas build -p android --profile production`
4. Complete store metadata (description, screenshots, privacy policy, support URL)
5. Upload builds and submit for review

If needed, add `eas.json` and store-specific config after final branding/package IDs are confirmed.

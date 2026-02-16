# Maverick Transaction Coordinator

Maverick is a Flask application for transaction coordination workflows:
- Agent contract upload
- S3 document storage
- PostgreSQL transaction tracking
- SMS notifications and auto-responses

## Week 1 deliverables in this scaffold

- Project structure and deployment files (`Procfile`, `runtime.txt`)
- Upload form UI (`templates/upload.html`)
- Upload API endpoint (`POST /upload`)
- Twilio SMS webhook (`POST /sms-webhook`)
- SQL schema (`schema.sql`)
- Helper utilities for database, Twilio, and S3 (`utils/`)
- Backup script (`backup_db.sh`)

## Local setup

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment:
   ```bash
   cp .env.example .env
   ```
4. Update `.env` with Railway, Twilio, AWS, and Stripe values.
5. Run app:
   ```bash
   python app.py
   ```
6. Open:
   - Upload UI: <http://localhost:5000>
   - Health check: <http://localhost:5000/health>

## Required environment variables

```env
DATABASE_URL=postgresql://user:pass@host:port/dbname
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_S3_BUCKET_DOCUMENTS=maverick-documents
AWS_S3_BUCKET_BACKUPS=maverick-backups
AWS_REGION=us-east-1
STRIPE_SECRET_KEY=
STRIPE_PUBLISHABLE_KEY=
SECRET_KEY=generate-random-secret-key
TC_USERNAME=margaret
TC_PASSWORD=secure-hashed-password
PAYPAL_EMAIL=pay@getmaverick.com
VENMO_HANDLE=@GetMaverick
HEIDI_PHONE=
MARGARET_PHONE=
```

## Deploy to Railway

1. Provision PostgreSQL in Railway.
2. Run `schema.sql` in the PostgreSQL query editor.
3. Deploy this directory from GitHub.
4. Add environment variables from `.env`.
5. Configure Twilio webhook to:
   ```
   https://<your-railway-domain>/sms-webhook
   ```

## Notes

- The `uploads/` folder is ignored and reserved for temporary local storage.
- The backup script expects `pg_dump` and `aws` CLI binaries in the runtime image.

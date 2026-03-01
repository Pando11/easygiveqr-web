# Maverick API Documentation

This document covers API-style routes used by mobile clients and the tokenized client portal.

## Authentication

### Mobile JWT

1. Obtain token:
   - `POST /api/mobile/login`
   - Body:
     ```json
     {
       "username": "margaret",
       "password": "your-tc-password"
     }
     ```
2. Use token:
   - Header: `Authorization: Bearer <access_token>`

## Mobile Endpoints

### Dashboard
- `GET /api/mobile/dashboard`

### Daily checklist
- `GET /api/mobile/daily-checklist`

### Task completion
- `POST /api/mobile/task/<task_id>/complete`
- Body:
  ```json
  { "completed": true }
  ```

### Call completion
- `POST /api/mobile/call/<deadline_id>/complete`
- Body:
  ```json
  { "made": true }
  ```

### Documents
- `GET /api/mobile/transaction/<transaction_id>/documents`

### Communications
- `GET /api/mobile/transaction/<transaction_id>/communications`
- `POST /api/mobile/transaction/<transaction_id>/communications`
- Body:
  ```json
  {
    "communication_type": "phone_call",
    "contact_party": "agent",
    "contact_name": "Optional Name",
    "summary": "Called to confirm timeline",
    "outcome": "Waiting on lender update",
    "follow_up_date": "2026-02-20"
  }
  ```

## Client Portal Endpoints

Client portal uses a unique token URL and does not require login credentials.

### Overview
- `GET /client/<access_token>`

### Timeline
- `GET /client/<access_token>/timeline`

### Documents + upload view
- `GET /client/<access_token>/documents`

### Upload signed document
- `POST /client/<access_token>/upload`
- Form fields:
  - `document_type`
  - `document_file` (pdf/jpg/jpeg/png)

## TC Utility Route

### Generate or re-send client portal links
- `POST /tc/transaction/<transaction_id>/generate-client-portal`

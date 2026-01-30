-- Migration: Create stripe_webhook_events table for tracking webhook events
-- Date: 2026-01-27
-- Description: Tracks Stripe webhook events for monitoring and debugging

CREATE TABLE IF NOT EXISTS public.stripe_webhook_events (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    event_id text UNIQUE,
    event_type text NOT NULL,
    processed_at timestamptz DEFAULT now() NOT NULL,
    status text NOT NULL CHECK (status IN ('success', 'error')),
    error_message text,
    created_at timestamptz DEFAULT now() NOT NULL
);

-- Index for querying recent events
CREATE INDEX IF NOT EXISTS idx_webhook_events_processed_at ON public.stripe_webhook_events(processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_events_event_type ON public.stripe_webhook_events(event_type);
CREATE INDEX IF NOT EXISTS idx_webhook_events_status ON public.stripe_webhook_events(status);
CREATE INDEX IF NOT EXISTS idx_webhook_events_event_id ON public.stripe_webhook_events(event_id);

COMMENT ON TABLE public.stripe_webhook_events IS 'Tracks Stripe webhook events for monitoring and debugging';
COMMENT ON COLUMN public.stripe_webhook_events.event_id IS 'Stripe event ID (evt_...)';
COMMENT ON COLUMN public.stripe_webhook_events.event_type IS 'Stripe event type (e.g., checkout.session.completed)';
COMMENT ON COLUMN public.stripe_webhook_events.status IS 'Processing status: success or error';

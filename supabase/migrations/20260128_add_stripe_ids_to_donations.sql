-- Migration: Add Stripe identifiers to donations table for reconciliation
-- Date: 2026-01-28
-- Description: Store Stripe payment intent, charge, and transfer IDs for payout reconciliation

-- Add stripe_payment_intent_id column
ALTER TABLE public.donations
ADD COLUMN IF NOT EXISTS stripe_payment_intent_id text;

-- Add stripe_charge_id column
ALTER TABLE public.donations
ADD COLUMN IF NOT EXISTS stripe_charge_id text;

-- Add stripe_transfer_id column
ALTER TABLE public.donations
ADD COLUMN IF NOT EXISTS stripe_transfer_id text;

-- Create indexes for reconciliation queries
CREATE INDEX IF NOT EXISTS idx_donations_payment_intent_id ON public.donations(stripe_payment_intent_id);
CREATE INDEX IF NOT EXISTS idx_donations_charge_id ON public.donations(stripe_charge_id);
CREATE INDEX IF NOT EXISTS idx_donations_transfer_id ON public.donations(stripe_transfer_id);

-- Add comments
COMMENT ON COLUMN public.donations.stripe_payment_intent_id IS 'Stripe Payment Intent ID (pi_...)';
COMMENT ON COLUMN public.donations.stripe_charge_id IS 'Stripe Charge ID (ch_...)';
COMMENT ON COLUMN public.donations.stripe_transfer_id IS 'Stripe Transfer ID (tr_...) if using transfers';

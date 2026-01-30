-- Migration: Add Stripe Connect fields to public.churches table
-- Date: 2026-01-27
-- Description: Adds Stripe Connect account fields for platform model payouts

-- Add stripe_account_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'stripe_account_id'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN stripe_account_id text;
        
        COMMENT ON COLUMN public.churches.stripe_account_id IS 'Stripe Connect account ID (acct_...) for this church';
    END IF;
END $$;

-- Add stripe_onboarding_status column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'stripe_onboarding_status'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN stripe_onboarding_status text DEFAULT 'not_started';
        
        COMMENT ON COLUMN public.churches.stripe_onboarding_status IS 'Stripe Connect onboarding status: not_started, pending, complete';
    END IF;
END $$;

-- Add stripe_charges_enabled column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'stripe_charges_enabled'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN stripe_charges_enabled boolean DEFAULT false;
        
        COMMENT ON COLUMN public.churches.stripe_charges_enabled IS 'Whether the connected account can accept charges';
    END IF;
END $$;

-- Add stripe_payouts_enabled column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'stripe_payouts_enabled'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN stripe_payouts_enabled boolean DEFAULT false;
        
        COMMENT ON COLUMN public.churches.stripe_payouts_enabled IS 'Whether the connected account can receive payouts';
    END IF;
END $$;

-- Add stripe_details_submitted column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'stripe_details_submitted'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN stripe_details_submitted boolean DEFAULT false;
        
        COMMENT ON COLUMN public.churches.stripe_details_submitted IS 'Whether required account details have been submitted to Stripe';
    END IF;
END $$;

-- Create index on stripe_account_id for efficient lookups
CREATE INDEX IF NOT EXISTS idx_churches_stripe_account_id ON public.churches(stripe_account_id);

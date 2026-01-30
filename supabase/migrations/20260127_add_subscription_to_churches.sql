-- Migration: Add subscription billing fields to public.churches table
-- Date: 2026-01-27
-- Description: Adds Stripe subscription fields for church billing ($29.95/month)

-- Add stripe_customer_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'stripe_customer_id'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN stripe_customer_id text;
        
        COMMENT ON COLUMN public.churches.stripe_customer_id IS 'Stripe Customer ID (cus_...) for subscription billing';
    END IF;
END $$;

-- Add stripe_subscription_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'stripe_subscription_id'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN stripe_subscription_id text;
        
        COMMENT ON COLUMN public.churches.stripe_subscription_id IS 'Stripe Subscription ID (sub_...) for monthly billing';
    END IF;
END $$;

-- Add subscription_status column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'subscription_status'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN subscription_status text CHECK (subscription_status IN ('active', 'past_due', 'canceled', 'trialing', 'incomplete', 'incomplete_expired', 'unpaid'));
        
        COMMENT ON COLUMN public.churches.subscription_status IS 'Current subscription status: active, past_due, canceled, trialing, etc.';
    END IF;
END $$;

-- Add subscription_started_at column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'subscription_started_at'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN subscription_started_at timestamptz;
        
        COMMENT ON COLUMN public.churches.subscription_started_at IS 'Timestamp when subscription was first activated';
    END IF;
END $$;

-- Add subscription_canceled_at column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'subscription_canceled_at'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN subscription_canceled_at timestamptz;
        
        COMMENT ON COLUMN public.churches.subscription_canceled_at IS 'Timestamp when subscription was canceled';
    END IF;
END $$;

-- Create index on stripe_customer_id for lookups
CREATE INDEX IF NOT EXISTS idx_churches_stripe_customer_id ON public.churches(stripe_customer_id);

-- Create index on stripe_subscription_id for lookups
CREATE INDEX IF NOT EXISTS idx_churches_stripe_subscription_id ON public.churches(stripe_subscription_id);

-- Create index on subscription_status for filtering
CREATE INDEX IF NOT EXISTS idx_churches_subscription_status ON public.churches(subscription_status);

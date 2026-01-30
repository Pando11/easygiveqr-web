-- Migration: Add donor identity columns to public.donations table
-- Date: 2026-01-27
-- Description: Adds donor_email, donor_name, and donor_address columns for tax receipt generation

-- Add donor_email column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'donations' 
        AND column_name = 'donor_email'
    ) THEN
        ALTER TABLE public.donations
        ADD COLUMN donor_email text;
        
        COMMENT ON COLUMN public.donations.donor_email IS 'Email address of the donor (from Stripe customer_details)';
    END IF;
END $$;

-- Add donor_name column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'donations' 
        AND column_name = 'donor_name'
    ) THEN
        ALTER TABLE public.donations
        ADD COLUMN donor_name text;
        
        COMMENT ON COLUMN public.donations.donor_name IS 'Name of the donor (from Stripe customer_details)';
    END IF;
END $$;

-- Add donor_address column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'donations' 
        AND column_name = 'donor_address'
    ) THEN
        ALTER TABLE public.donations
        ADD COLUMN donor_address jsonb;
        
        COMMENT ON COLUMN public.donations.donor_address IS 'Address of the donor as JSON (from Stripe customer_details.address)';
    END IF;
END $$;

-- Create index on donor_email if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_donations_donor_email ON public.donations(donor_email);

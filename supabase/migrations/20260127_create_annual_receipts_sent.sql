-- Migration: Create annual_receipts_sent table for idempotency
-- Date: 2026-01-27
-- Description: Tracks which annual receipts have been sent to prevent duplicate emails

CREATE TABLE IF NOT EXISTS public.annual_receipts_sent (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    year integer NOT NULL,
    church_id text NOT NULL,
    donor_email text NOT NULL,
    sent_at timestamptz DEFAULT now() NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    
    -- Unique constraint to prevent duplicate sends
    CONSTRAINT annual_receipts_sent_unique UNIQUE (year, church_id, donor_email)
);

-- Add foreign key constraint to churches table if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = 'churches'
    ) THEN
        -- Check if foreign key doesn't exist
        IF NOT EXISTS (
            SELECT 1 
            FROM information_schema.table_constraints 
            WHERE constraint_schema = 'public' 
            AND table_name = 'annual_receipts_sent' 
            AND constraint_name = 'annual_receipts_sent_church_id_fkey'
        ) THEN
            ALTER TABLE public.annual_receipts_sent
            ADD CONSTRAINT annual_receipts_sent_church_id_fkey 
            FOREIGN KEY (church_id) REFERENCES public.churches(church_id) ON DELETE CASCADE;
        END IF;
    END IF;
END $$;

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_annual_receipts_sent_year_church ON public.annual_receipts_sent(year, church_id);
CREATE INDEX IF NOT EXISTS idx_annual_receipts_sent_donor_email ON public.annual_receipts_sent(donor_email);

COMMENT ON TABLE public.annual_receipts_sent IS 'Tracks annual tax receipts sent to donors to prevent duplicate emails';
COMMENT ON COLUMN public.annual_receipts_sent.year IS 'Tax year for the receipt';
COMMENT ON COLUMN public.annual_receipts_sent.church_id IS 'Church that received the donations';
COMMENT ON COLUMN public.annual_receipts_sent.donor_email IS 'Email address of the donor who received the receipt';

-- Migration: Ensure donations table has required unique constraints
-- Date: 2026-01-28
-- Description: Adds unique constraint on stripe_session_id if missing (critical for idempotency)

-- Check if stripe_session_id unique constraint exists, if not add it
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint 
    WHERE conname = 'donations_stripe_session_id_key'
    AND conrelid = 'public.donations'::regclass
  ) THEN
    -- Add unique constraint on stripe_session_id (critical for webhook idempotency)
    ALTER TABLE public.donations
    ADD CONSTRAINT donations_stripe_session_id_key UNIQUE (stripe_session_id);
    
    RAISE NOTICE 'Added unique constraint on donations.stripe_session_id';
  ELSE
    RAISE NOTICE 'Unique constraint on donations.stripe_session_id already exists';
  END IF;
END $$;

-- Verify foreign key constraint exists
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint 
    WHERE conname LIKE '%donations_church_id%'
    AND conrelid = 'public.donations'::regclass
  ) THEN
    -- Add foreign key if missing
    ALTER TABLE public.donations
    ADD CONSTRAINT donations_church_id_fkey 
    FOREIGN KEY (church_id) REFERENCES public.churches(church_id) ON DELETE CASCADE;
    
    RAISE NOTICE 'Added foreign key constraint on donations.church_id';
  ELSE
    RAISE NOTICE 'Foreign key constraint on donations.church_id already exists';
  END IF;
END $$;

-- Add comment
COMMENT ON CONSTRAINT donations_stripe_session_id_key ON public.donations IS 
  'Ensures idempotency: duplicate webhook events cannot create duplicate donation rows';

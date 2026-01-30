-- Migration: Add status constraint to churches table
-- Date: 2026-01-28
-- Description: Ensure status is one of: pending, active, paused, closed

-- First, update any invalid statuses to 'pending'
UPDATE public.churches
SET status = 'pending'
WHERE status IS NULL OR status NOT IN ('pending', 'active', 'paused', 'closed');

-- Add constraint if it doesn't exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint 
    WHERE conname = 'churches_status_check'
  ) THEN
    ALTER TABLE public.churches
    ADD CONSTRAINT churches_status_check 
    CHECK (status IN ('pending', 'active', 'paused', 'closed'));
  END IF;
END $$;

-- Add activated_at column if it doesn't exist
ALTER TABLE public.churches
ADD COLUMN IF NOT EXISTS activated_at timestamptz;

-- Add comments
COMMENT ON COLUMN public.churches.status IS 'Church status: pending, active, paused, or closed';
COMMENT ON COLUMN public.churches.activated_at IS 'Timestamp when church status was set to active';

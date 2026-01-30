-- Migration: Add donations_paused column to churches table
-- Date: 2026-01-28
-- Description: Per-church pause flag for emergency kill switch

ALTER TABLE public.churches
ADD COLUMN IF NOT EXISTS donations_paused boolean NOT NULL DEFAULT false;

-- Add comment
COMMENT ON COLUMN public.churches.donations_paused IS 'If true, donations are paused for this church (emergency kill switch)';

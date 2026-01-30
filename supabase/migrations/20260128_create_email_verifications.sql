-- Migration: Create email_verifications table for email verification workflow
-- Date: 2026-01-28
-- Description: Tracks email verification status for church admin emails

CREATE TABLE IF NOT EXISTS public.email_verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  church_id text NOT NULL REFERENCES public.churches(church_id) ON DELETE CASCADE,
  email text NOT NULL,
  token text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified')),
  created_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz,

  -- Ensure one verification per church+email combination
  UNIQUE(church_id, email)
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_email_verifications_church_id ON public.email_verifications(church_id);
CREATE INDEX IF NOT EXISTS idx_email_verifications_email ON public.email_verifications(email);
CREATE INDEX IF NOT EXISTS idx_email_verifications_token ON public.email_verifications(token);
CREATE INDEX IF NOT EXISTS idx_email_verifications_status ON public.email_verifications(status);

-- Add comments
COMMENT ON TABLE public.email_verifications IS 'Tracks email verification status for church admin emails';
COMMENT ON COLUMN public.email_verifications.token IS 'Unique verification token (UUID)';
COMMENT ON COLUMN public.email_verifications.status IS 'Verification status: pending or verified';

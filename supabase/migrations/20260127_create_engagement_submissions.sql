-- Create engagement_submissions table for prayer requests, visitor cards, and volunteer interest
-- Unified table with type column for simplicity

CREATE TABLE IF NOT EXISTS public.engagement_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  church_id text NOT NULL REFERENCES public.churches(church_id) ON DELETE CASCADE,
  type text NOT NULL CHECK (type IN ('prayer', 'visitor', 'volunteer')),
  name text,
  email text,
  phone text,
  message text,
  meta jsonb,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  
  -- Indexes for common queries
  CONSTRAINT engagement_submissions_church_id_fkey FOREIGN KEY (church_id) REFERENCES public.churches(church_id) ON DELETE CASCADE
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_engagement_submissions_church_id ON public.engagement_submissions(church_id);
CREATE INDEX IF NOT EXISTS idx_engagement_submissions_type ON public.engagement_submissions(type);
CREATE INDEX IF NOT EXISTS idx_engagement_submissions_status ON public.engagement_submissions(status);
CREATE INDEX IF NOT EXISTS idx_engagement_submissions_created_at ON public.engagement_submissions(created_at DESC);

-- Add comment for documentation
COMMENT ON TABLE public.engagement_submissions IS 'Prayer requests, visitor connect cards, and volunteer interest submissions';
COMMENT ON COLUMN public.engagement_submissions.type IS 'Type of submission: prayer, visitor, or volunteer';
COMMENT ON COLUMN public.engagement_submissions.meta IS 'Additional fields stored as JSON (e.g., areas_of_interest for volunteers)';
COMMENT ON COLUMN public.engagement_submissions.status IS 'Status: open or completed';

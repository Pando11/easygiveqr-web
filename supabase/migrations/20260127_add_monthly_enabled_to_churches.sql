-- Add monthly_enabled column to churches table
-- This flag controls whether a church can accept monthly recurring donations

ALTER TABLE public.churches
ADD COLUMN IF NOT EXISTS monthly_enabled boolean NOT NULL DEFAULT false;

-- Add comment for documentation
COMMENT ON COLUMN public.churches.monthly_enabled IS 'Whether monthly recurring donations are enabled for this church';

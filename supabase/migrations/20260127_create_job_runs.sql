-- Migration: Create job_runs table for tracking batch job executions
-- Date: 2026-01-27
-- Description: Tracks job execution history for monitoring and debugging

CREATE TABLE IF NOT EXISTS public.job_runs (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    job_name text NOT NULL,
    started_at timestamptz DEFAULT now() NOT NULL,
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('success', 'error')),
    summary jsonb,
    error text,
    created_at timestamptz DEFAULT now() NOT NULL
);

-- Index for querying by job name and date
CREATE INDEX IF NOT EXISTS idx_job_runs_job_name ON public.job_runs(job_name);
CREATE INDEX IF NOT EXISTS idx_job_runs_started_at ON public.job_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_runs_status ON public.job_runs(status);

-- Index for recent runs
CREATE INDEX IF NOT EXISTS idx_job_runs_recent ON public.job_runs(started_at DESC, job_name);

COMMENT ON TABLE public.job_runs IS 'Tracks execution history of batch jobs (weekly-summary, annual-receipts, wednesday-payouts)';
COMMENT ON COLUMN public.job_runs.job_name IS 'Name of the job (e.g., weekly-summary, annual-receipts)';
COMMENT ON COLUMN public.job_runs.status IS 'Job execution status: success or error';
COMMENT ON COLUMN public.job_runs.summary IS 'JSON summary of job execution (e.g., churches processed, emails sent)';
COMMENT ON COLUMN public.job_runs.error IS 'Error message if status is error';

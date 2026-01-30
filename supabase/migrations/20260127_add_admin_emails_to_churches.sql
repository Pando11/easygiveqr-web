-- Migration: Add admin_emails column to public.churches table
-- Date: 2026-01-27
-- Description: Adds admin_emails text array column for storing church administrator email addresses

-- Add admin_emails column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'admin_emails'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN admin_emails text[] NOT NULL DEFAULT '{}';
        
        COMMENT ON COLUMN public.churches.admin_emails IS 'Array of email addresses for church administrators who receive weekly summary emails';
    END IF;
END $$;

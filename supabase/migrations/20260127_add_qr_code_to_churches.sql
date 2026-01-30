-- Migration: Add QR code fields to public.churches table
-- Date: 2026-01-27
-- Description: Adds QR code URL and updated timestamp for church donation QR codes

-- Add qr_code_url column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'qr_code_url'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN qr_code_url text;
        
        COMMENT ON COLUMN public.churches.qr_code_url IS 'Public URL to the stored QR code image (PNG)';
    END IF;
END $$;

-- Add qr_code_updated_at column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name = 'churches' 
        AND column_name = 'qr_code_updated_at'
    ) THEN
        ALTER TABLE public.churches
        ADD COLUMN qr_code_updated_at timestamptz;
        
        COMMENT ON COLUMN public.churches.qr_code_updated_at IS 'Timestamp when the QR code was last generated/updated';
    END IF;
END $$;

import { createClient } from "@supabase/supabase-js";

/**
 * Server-only Supabase admin client using service role key.
 * This client bypasses Row Level Security (RLS) policies.
 * 
 * @returns Supabase client configured with service role
 * @throws Error if required environment variables are missing
 */
export function getSupabaseAdmin() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl) {
    throw new Error("SUPABASE_URL environment variable is required");
  }

  if (!serviceRoleKey) {
    throw new Error("SUPABASE_SERVICE_ROLE_KEY environment variable is required");
  }

  return createClient(supabaseUrl, serviceRoleKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });
}

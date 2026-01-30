import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";
import Stripe from "stripe";

export const runtime = "nodejs";

/**
 * GET handler for admin health check
 * 
 * Protected by x-admin-secret
 * Returns detailed health information including:
 * - Stripe live mode status (not secret values)
 * - Last webhook event timestamp
 * - Last cron run status
 * - Kill switch status
 */
export async function GET(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const health: Record<string, any> = {
      ok: true,
      timestamp: new Date().toISOString(),
      environment: process.env.NODE_ENV || "unknown",
    };

    // Check global kill switch
    health.kill_switch = {
      donations_paused: process.env.DONATIONS_PAUSED === "true",
    };

    // Check Stripe configuration (without exposing secrets)
    try {
      const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
      if (stripeSecretKey) {
        const stripe = new Stripe(stripeSecretKey, {
          apiVersion: "2025-12-15.clover",
        });
        
        // Get account info (doesn't expose secrets)
        // Note: In Stripe API 2025-12-15.clover, accounts.retrieve() returns Account directly
        const accountResponse = await stripe.accounts.retrieve();
        // Handle both Response<Account> and Account types
        const account = accountResponse as any; // Type assertion for compatibility
        health.stripe = {
          live_mode: account?.livemode ?? false,
          charges_enabled: account?.charges_enabled ?? false,
          payouts_enabled: account?.payouts_enabled ?? false,
          country: account?.country ?? "US",
        };
      } else {
        health.stripe = { error: "STRIPE_SECRET_KEY not configured" };
      }
    } catch (err: any) {
      health.stripe = { error: err?.message || "Failed to connect to Stripe" };
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      health.supabase = { error: "Failed to initialize Supabase client" };
      return NextResponse.json(health, { status: 500 });
    }

    // Get last webhook event
    try {
      const { data: lastEvent, error: eventError } = await supabase
        .from("stripe_webhook_events")
        .select("processed_at, event_type, status")
        .order("processed_at", { ascending: false })
        .limit(1)
        .maybeSingle();

      if (!eventError && lastEvent) {
        health.webhook = {
          last_event_at: lastEvent.processed_at,
          last_event_type: lastEvent.event_type,
          last_event_status: lastEvent.status,
        };
      } else {
        health.webhook = { last_event_at: null, note: "No webhook events found" };
      }
    } catch (err: any) {
      health.webhook = { error: "Failed to query webhook events" };
    }

    // Get last cron run status
    try {
      const { data: lastJob, error: jobError } = await supabase
        .from("job_runs")
        .select("job_name, started_at, finished_at, status")
        .order("started_at", { ascending: false })
        .limit(3);

      if (!jobError && lastJob) {
        health.cron = {
          recent_runs: lastJob.map((job) => ({
            job_name: job.job_name,
            started_at: job.started_at,
            finished_at: job.finished_at,
            status: job.status,
          })),
        };
      } else {
        health.cron = { note: "No recent job runs found" };
      }
    } catch (err: any) {
      health.cron = { error: "Failed to query job runs" };
    }

    // Check database connectivity
    try {
      const { error: dbError } = await supabase.from("churches").select("church_id").limit(1);
      health.database = {
        connected: !dbError,
        error: dbError?.message || null,
      };
    } catch (err: any) {
      health.database = { connected: false, error: err?.message };
    }

    return NextResponse.json(health);
  } catch (err: any) {
    console.error("[Admin Health] Unexpected error", err);
    return NextResponse.json(
      {
        ok: false,
        error: "Internal server error",
        message: err?.message,
      },
      { status: 500 }
    );
  }
}

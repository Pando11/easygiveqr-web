import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * GET handler for webhook health check
 * 
 * Returns:
 * - 200: Webhook health status with recent event counts
 * - 401: Unauthorized
 */
export async function GET(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Webhook Health] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Get last webhook event
    const { data: lastEvent, error: lastEventError } = await supabase
      .from("stripe_webhook_events")
      .select("processed_at, event_type, status")
      .order("processed_at", { ascending: false })
      .limit(1)
      .single();

    // Get webhook events count in last 24 hours
    const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
    const { count: webhookCount, error: webhookCountError } = await supabase
      .from("stripe_webhook_events")
      .select("*", { count: "exact", head: true })
      .gte("processed_at", twentyFourHoursAgo.toISOString());

    // Get donations count in last 24 hours
    const { count: donationCount, error: donationCountError } = await supabase
      .from("donations")
      .select("*", { count: "exact", head: true })
      .gte("created_at", twentyFourHoursAgo.toISOString());

    // Get error count in last 24 hours
    const { count: errorCount, error: errorCountError } = await supabase
      .from("stripe_webhook_events")
      .select("*", { count: "exact", head: true })
      .gte("processed_at", twentyFourHoursAgo.toISOString())
      .eq("status", "error");

    // Check for errors
    if (lastEventError && lastEventError.code !== "PGRST116") {
      // PGRST116 is "no rows found", which is OK
      console.error("[Webhook Health] Error fetching last event", {
        error: lastEventError.message,
      });
    }

    if (webhookCountError) {
      console.error("[Webhook Health] Error counting webhook events", {
        error: webhookCountError.message,
      });
    }

    if (donationCountError) {
      console.error("[Webhook Health] Error counting donations", {
        error: donationCountError.message,
      });
    }

    if (errorCountError) {
      console.error("[Webhook Health] Error counting errors", {
        error: errorCountError.message,
      });
    }

    return NextResponse.json({
      ok: true,
      last_webhook_event: lastEvent
        ? {
            processed_at: lastEvent.processed_at,
            event_type: lastEvent.event_type,
            status: lastEvent.status,
          }
        : null,
      last_24_hours: {
        webhook_events: webhookCount || 0,
        donations: donationCount || 0,
        webhook_errors: errorCount || 0,
      },
      timestamp: new Date().toISOString(),
    });
  } catch (err: any) {
    console.error("[Webhook Health] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

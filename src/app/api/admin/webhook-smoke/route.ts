import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * GET handler for webhook smoke test / health check
 * 
 * Returns:
 * - lastWebhookAt: Timestamp of most recent webhook event
 * - count24h: Count of webhook events in last 24 hours
 * - count1h: Count of webhook events in last 1 hour
 * 
 * Uses stripe_webhook_events table if present; otherwise falls back to donations recency
 * Protected by x-admin-secret
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
      console.error("[Webhook Smoke] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Try to use stripe_webhook_events table first
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
    const twentyFourHoursAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);

    // Check if stripe_webhook_events table exists by querying it
    const { data: lastEvent, error: eventError } = await supabase
      .from("stripe_webhook_events")
      .select("processed_at")
      .order("processed_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    if (!eventError && lastEvent) {
      // Table exists and has data - use it
      const { count: count24h } = await supabase
        .from("stripe_webhook_events")
        .select("*", { count: "exact", head: true })
        .gte("processed_at", twentyFourHoursAgo.toISOString());

      const { count: count1h } = await supabase
        .from("stripe_webhook_events")
        .select("*", { count: "exact", head: true })
        .gte("processed_at", oneHourAgo.toISOString());

      return NextResponse.json({
        ok: true,
        lastWebhookAt: lastEvent.processed_at,
        count24h: count24h || 0,
        count1h: count1h || 0,
        source: "stripe_webhook_events",
        timestamp: new Date().toISOString(),
      });
    }

    // Fallback: Use donations table to infer webhook activity
    const { data: lastDonation, error: donationError } = await supabase
      .from("donations")
      .select("created_at")
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle();

    if (donationError && donationError.code !== "PGRST116") {
      // Error other than "no rows found"
      console.error("[Webhook Smoke] Error querying donations", {
        error: donationError.message,
      });
    }

    const { count: donationCount24h } = await supabase
      .from("donations")
      .select("*", { count: "exact", head: true })
      .gte("created_at", twentyFourHoursAgo.toISOString());

    const { count: donationCount1h } = await supabase
      .from("donations")
      .select("*", { count: "exact", head: true })
      .gte("created_at", oneHourAgo.toISOString());

    return NextResponse.json({
      ok: true,
      lastWebhookAt: lastDonation?.created_at || null,
      count24h: donationCount24h || 0,
      count1h: donationCount1h || 0,
      source: "donations",
      note: "Using donations table as fallback (stripe_webhook_events may not exist)",
      timestamp: new Date().toISOString(),
    });
  } catch (err: any) {
    console.error("[Webhook Smoke] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

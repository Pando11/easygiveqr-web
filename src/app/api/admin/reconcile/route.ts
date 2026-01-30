import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * GET handler for reconciliation report
 * 
 * Query parameters:
 * - church_id: Church ID (required)
 * - from: Start date (YYYY-MM-DD, optional, defaults to 30 days ago)
 * - to: End date (YYYY-MM-DD, optional, defaults to today)
 * 
 * Returns:
 * - 200: Reconciliation report with totals, recent donations, and anomalies
 * - 400: Missing church_id
 * - 401: Unauthorized
 * - 404: Church not found
 */
export async function GET(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    // Get query parameters
    const { searchParams } = new URL(req.url);
    const church_id = searchParams.get("church_id");
    const fromParam = searchParams.get("from");
    const toParam = searchParams.get("to");

    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required parameter: church_id" },
        { status: 400 }
      );
    }

    // Parse dates (default to last 30 days if not provided)
    const to = toParam ? new Date(toParam + "T23:59:59Z") : new Date();
    const from = fromParam
      ? new Date(fromParam + "T00:00:00Z")
      : new Date(Date.now() - 30 * 24 * 60 * 60 * 1000); // 30 days ago

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Reconcile] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Verify church exists
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, display_name")
      .eq("church_id", church_id)
      .single();

    if (churchError) {
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // Get total donations in date range
    const { data: donations, error: donationsError } = await supabase
      .from("donations")
      .select("stripe_session_id, amount_cents, created_at, status, church_id")
      .eq("church_id", church_id)
      .gte("created_at", from.toISOString())
      .lte("created_at", to.toISOString())
      .order("created_at", { ascending: false });

    if (donationsError) {
      console.error("[Reconcile] Failed to fetch donations", {
        error: donationsError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Database error" },
        { status: 500 }
      );
    }

    // Calculate totals
    const totalCount = donations?.length || 0;
    const totalAmount = donations?.reduce((sum, d) => sum + (d.amount_cents || 0), 0) || 0;

    // Get last 20 donations
    const recentDonations = (donations || []).slice(0, 20).map((d) => ({
      stripe_session_id: d.stripe_session_id,
      amount_cents: d.amount_cents,
      created_at: d.created_at,
      status: d.status,
    }));

    // Check for anomalies
    const anomalies: string[] = [];

    // Check for missing church_id
    const missingChurchId = donations?.filter((d) => !d.church_id || d.church_id.trim().length === 0);
    if (missingChurchId && missingChurchId.length > 0) {
      anomalies.push(`Found ${missingChurchId.length} donation(s) with missing church_id`);
    }

    // Check for zero amounts
    const zeroAmounts = donations?.filter((d) => !d.amount_cents || d.amount_cents === 0);
    if (zeroAmounts && zeroAmounts.length > 0) {
      anomalies.push(`Found ${zeroAmounts.length} donation(s) with amount_cents = 0`);
    }

    // Check for duplicate stripe_session_id
    const sessionIds = donations?.map((d) => d.stripe_session_id) || [];
    const uniqueSessionIds = new Set(sessionIds);
    if (sessionIds.length !== uniqueSessionIds.size) {
      const duplicates = sessionIds.filter(
        (id, index) => sessionIds.indexOf(id) !== index
      );
      anomalies.push(
        `Found ${duplicates.length} duplicate stripe_session_id(s): ${duplicates.slice(0, 5).join(", ")}`
      );
    }

    return NextResponse.json({
      ok: true,
      church_id,
      church_name: church.display_name,
      date_range: {
        from: from.toISOString().split("T")[0],
        to: to.toISOString().split("T")[0],
      },
      totals: {
        count: totalCount,
        amount_cents: totalAmount,
        amount_dollars: (totalAmount / 100).toFixed(2),
      },
      recent_donations: recentDonations,
      anomalies: anomalies.length > 0 ? anomalies : null,
    });
  } catch (err: any) {
    console.error("[Reconcile] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

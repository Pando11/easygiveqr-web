import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * GET handler to fetch church billing information
 * 
 * Query parameters:
 * - church_id: Church ID (required)
 * 
 * Returns:
 * - 200: Church billing information
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

    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required parameter: church_id" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Billing Get Church] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church billing information
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select(
        "church_id, stripe_customer_id, stripe_subscription_id, subscription_status, subscription_started_at, subscription_canceled_at"
      )
      .eq("church_id", church_id)
      .single();

    if (churchError) {
      console.error("[Billing Get Church] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    return NextResponse.json({
      ok: true,
      church_id: church.church_id,
      stripe_customer_id: church.stripe_customer_id,
      stripe_subscription_id: church.stripe_subscription_id,
      subscription_status: church.subscription_status,
      subscription_started_at: church.subscription_started_at,
      subscription_canceled_at: church.subscription_canceled_at,
    });
  } catch (err: any) {
    console.error("[Billing Get Church] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

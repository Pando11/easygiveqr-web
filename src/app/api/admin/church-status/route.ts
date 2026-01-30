import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * GET handler to get church Stripe Connect status
 * 
 * Query parameters:
 * - church_id: Church ID (required)
 * 
 * Protected by x-admin-secret
 * Returns Stripe Connect onboarding status
 */
export async function GET(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

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
      console.error("[Church Status] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church Stripe Connect status
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select(
        "church_id, display_name, stripe_account_id, stripe_charges_enabled, stripe_payouts_enabled, stripe_details_submitted, stripe_onboarding_status"
      )
      .eq("church_id", church_id)
      .single();

    if (churchError || !church) {
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    return NextResponse.json({
      ok: true,
      church_id: church.church_id,
      display_name: church.display_name,
      stripe: {
        account_id: church.stripe_account_id || null,
        charges_enabled: church.stripe_charges_enabled || false,
        payouts_enabled: church.stripe_payouts_enabled || false,
        details_submitted: church.stripe_details_submitted || false,
        onboarding_status: church.stripe_onboarding_status || "not_started",
      },
    });
  } catch (err: any) {
    console.error("[Church Status] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

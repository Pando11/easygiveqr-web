import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";
import Stripe from "stripe";
import { getSiteUrl } from "@/lib/siteUrl";

export const runtime = "nodejs";

/**
 * POST handler to generate a fresh Stripe Connect onboarding link
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123"
 * }
 * 
 * Protected by x-admin-secret
 * Returns a fresh Stripe onboarding link
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));
    const church_id = String(body?.church_id || "");

    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
    if (!stripeSecretKey) {
      return NextResponse.json(
        { ok: false, error: "STRIPE_SECRET_KEY not configured" },
        { status: 500 }
      );
    }

    const stripe = new Stripe(stripeSecretKey, {
      apiVersion: "2025-12-15.clover",
    });

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Onboarding Link] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, stripe_account_id")
      .eq("church_id", church_id)
      .single();

    if (churchError || !church) {
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    if (!church.stripe_account_id) {
      return NextResponse.json(
        { ok: false, error: "Church has no Stripe Connect account" },
        { status: 400 }
      );
    }

    // Get site URL
    let siteUrl: string;
    try {
      siteUrl = getSiteUrl();
    } catch (err: any) {
      return NextResponse.json(
        { ok: false, error: "Site URL not configured" },
        { status: 500 }
      );
    }

    // Generate onboarding link
    const returnUrl = `${siteUrl}/admin/onboarding/complete?church_id=${encodeURIComponent(church_id)}`;
    const refreshUrl = `${siteUrl}/admin/onboarding?church_id=${encodeURIComponent(church_id)}`;

    const accountLink = await stripe.accountLinks.create({
      account: church.stripe_account_id,
      refresh_url: refreshUrl,
      return_url: returnUrl,
      type: "account_onboarding",
    });

    // Update onboarding status
    await supabase
      .from("churches")
      .update({ stripe_onboarding_status: "pending" })
      .eq("church_id", church_id);

    return NextResponse.json({
      ok: true,
      church_id,
      onboarding_url: accountLink.url,
      expires_at: new Date(accountLink.expires_at * 1000).toISOString(),
    });
  } catch (err: any) {
    console.error("[Onboarding Link] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: err?.message || "Internal server error" },
      { status: 500 }
    );
  }
}

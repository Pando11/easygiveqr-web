import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * POST handler to generate Stripe Connect onboarding link
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123",
 *   "return_url": "https://example.com/onboarding/complete",
 *   "refresh_url": "https://example.com/onboarding"
 * }
 * 
 * Environment variables required:
 * - STRIPE_SECRET_KEY: Stripe secret key (platform account)
 * - SUPABASE_URL: Supabase project URL
 * - SUPABASE_SERVICE_ROLE_KEY: Supabase service role key
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    // Validate required environment variables
    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;

    if (!stripeSecretKey) {
      console.error("[Connect Onboarding Link] Missing STRIPE_SECRET_KEY");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Initialize Stripe client
    const stripe = new Stripe(stripeSecretKey, {
      apiVersion: "2025-12-15.clover",
    });

    // Parse request body
    let body: { church_id?: string; return_url?: string; refresh_url?: string };
    try {
      body = await req.json();
    } catch {
      return NextResponse.json(
        { ok: false, error: "Invalid JSON body" },
        { status: 400 }
      );
    }

    const church_id = body.church_id;
    const return_url = body.return_url;
    const refresh_url = body.refresh_url;

    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    if (!return_url) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: return_url" },
        { status: 400 }
      );
    }

    if (!refresh_url) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: refresh_url" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Connect Onboarding Link] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church to get stripe_account_id
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, stripe_account_id")
      .eq("church_id", church_id)
      .single();

    if (churchError) {
      console.error("[Connect Onboarding Link] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    if (!church.stripe_account_id) {
      return NextResponse.json(
        { ok: false, error: "Church does not have a Stripe account. Create account first." },
        { status: 400 }
      );
    }

    // Create account link for onboarding
    const accountLink = await stripe.accountLinks.create({
      account: church.stripe_account_id,
      refresh_url: refresh_url,
      return_url: return_url,
      type: "account_onboarding",
    });

    // Update onboarding status to pending
    await supabase
      .from("churches")
      .update({ stripe_onboarding_status: "pending" })
      .eq("church_id", church_id);

    return NextResponse.json({
      ok: true,
      url: accountLink.url,
    });
  } catch (err: any) {
    console.error("[Connect Onboarding Link] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * POST handler to sync Stripe Connect account status
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123"
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
      console.error("[Connect Sync Status] Missing STRIPE_SECRET_KEY");
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
    let body: { church_id?: string };
    try {
      body = await req.json();
    } catch {
      return NextResponse.json(
        { ok: false, error: "Invalid JSON body" },
        { status: 400 }
      );
    }

    const church_id = body.church_id;

    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Connect Sync Status] Failed to initialize Supabase client");
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
      console.error("[Connect Sync Status] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    if (!church.stripe_account_id) {
      return NextResponse.json(
        { ok: false, error: "Church does not have a Stripe account" },
        { status: 400 }
      );
    }

    // Retrieve account from Stripe
    const account = await stripe.accounts.retrieve(church.stripe_account_id);

    // Determine onboarding status
    let onboardingStatus: "not_started" | "pending" | "complete" = "not_started";
    
    if (account.details_submitted && account.charges_enabled && account.payouts_enabled) {
      onboardingStatus = "complete";
    } else if (account.details_submitted || account.charges_enabled || account.payouts_enabled) {
      onboardingStatus = "pending";
    }

    // Update church with account status
    const { error: updateError } = await supabase
      .from("churches")
      .update({
        stripe_onboarding_status: onboardingStatus,
        stripe_charges_enabled: account.charges_enabled || false,
        stripe_payouts_enabled: account.payouts_enabled || false,
        stripe_details_submitted: account.details_submitted || false,
      })
      .eq("church_id", church_id);

    if (updateError) {
      console.error("[Connect Sync Status] Failed to update church", {
        error: updateError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Database error" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      status: {
        stripe_account_id: account.id,
        onboarding_status: onboardingStatus,
        charges_enabled: account.charges_enabled || false,
        payouts_enabled: account.payouts_enabled || false,
        details_submitted: account.details_submitted || false,
      },
    });
  } catch (err: any) {
    console.error("[Connect Sync Status] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

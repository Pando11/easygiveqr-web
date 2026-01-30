import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * POST handler to create or retrieve Stripe Connect account for a church
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
      console.error("[Connect Create Account] Missing STRIPE_SECRET_KEY");
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
      console.error("[Connect Create Account] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church to check if account already exists
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, stripe_account_id, legal_name, display_name")
      .eq("church_id", church_id)
      .single();

    if (churchError) {
      console.error("[Connect Create Account] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // If account already exists, return it
    if (church.stripe_account_id) {
      return NextResponse.json({
        ok: true,
        stripe_account_id: church.stripe_account_id,
      });
    }

    // Create new Stripe Connect Express account
    const account = await stripe.accounts.create({
      type: "express",
      country: "US", // Default to US, can be made configurable
      capabilities: {
        card_payments: { requested: true },
        transfers: { requested: true },
      },
      metadata: {
        church_id: church_id,
      },
    });

    // Update church with stripe_account_id
    const { error: updateError } = await supabase
      .from("churches")
      .update({
        stripe_account_id: account.id,
        stripe_onboarding_status: "not_started",
        stripe_charges_enabled: false,
        stripe_payouts_enabled: false,
        stripe_details_submitted: false,
      })
      .eq("church_id", church_id);

    if (updateError) {
      console.error("[Connect Create Account] Failed to update church", {
        error: updateError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Database error" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      stripe_account_id: account.id,
    });
  } catch (err: any) {
    console.error("[Connect Create Account] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

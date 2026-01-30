import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * POST handler to create Stripe Customer for a church
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
      console.error("[Billing Create Customer] Missing STRIPE_SECRET_KEY");
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
      console.error("[Billing Create Customer] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, display_name, legal_name, admin_emails, stripe_customer_id")
      .eq("church_id", church_id)
      .single();

    if (churchError) {
      console.error("[Billing Create Customer] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // If customer already exists, return it
    if (church.stripe_customer_id) {
      return NextResponse.json({
        ok: true,
        stripe_customer_id: church.stripe_customer_id,
        message: "Customer already exists",
      });
    }

    // Get first admin email for customer email
    const customerEmail = church.admin_emails && church.admin_emails.length > 0
      ? church.admin_emails[0]
      : null;

    // Create Stripe Customer
    const customer = await stripe.customers.create({
      email: customerEmail || undefined,
      name: church.display_name || church.legal_name || undefined,
      metadata: {
        church_id: church_id,
      },
    });

    // Update church with customer ID
    const { error: updateError } = await supabase
      .from("churches")
      .update({
        stripe_customer_id: customer.id,
      })
      .eq("church_id", church_id);

    if (updateError) {
      console.error("[Billing Create Customer] Failed to update church", {
        error: updateError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Database error" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      stripe_customer_id: customer.id,
    });
  } catch (err: any) {
    console.error("[Billing Create Customer] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

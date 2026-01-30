import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";
import { getSiteUrl } from "@/lib/siteUrl";

export const runtime = "nodejs";

const SUBSCRIPTION_PRICE_AMOUNT = 2995; // $29.95 in cents
const SUBSCRIPTION_PRICE_CURRENCY = "usd";

/**
 * Get or create the subscription price in Stripe
 * This creates the price once if it doesn't exist
 */
async function getOrCreateSubscriptionPrice(stripe: Stripe): Promise<string> {
  // Try to find existing price first
  const prices = await stripe.prices.list({
    active: true,
    type: "recurring",
    limit: 100,
  });

  // Look for $29.95/month price
  const existingPrice = prices.data.find(
    (price) =>
      price.unit_amount === SUBSCRIPTION_PRICE_AMOUNT &&
      price.currency === SUBSCRIPTION_PRICE_CURRENCY &&
      price.recurring?.interval === "month"
  );

  if (existingPrice) {
    return existingPrice.id;
  }

  // Create product and price if not found
  const product = await stripe.products.create({
    name: "EasyGiveQR Monthly Subscription",
    description: "Monthly subscription for EasyGiveQR platform access",
  });

  const price = await stripe.prices.create({
    product: product.id,
    unit_amount: SUBSCRIPTION_PRICE_AMOUNT,
    currency: SUBSCRIPTION_PRICE_CURRENCY,
    recurring: {
      interval: "month",
    },
  });

  return price.id;
}

/**
 * POST handler to create Stripe Checkout Session for subscription purchase
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123",
 *   "success_url": "https://your-domain.com/billing/success",
 *   "cancel_url": "https://your-domain.com/billing/cancel"
 * }
 * 
 * Environment variables required:
 * - STRIPE_SECRET_KEY: Stripe secret key (platform account)
 * - SUPABASE_URL: Supabase project URL
 * - SUPABASE_SERVICE_ROLE_KEY: Supabase service role key
 * - NEXT_PUBLIC_SITE_URL or SITE_URL: Base URL for return URLs
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    // Validate required environment variables
    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;

    if (!stripeSecretKey) {
      console.error("[Billing Create Subscription Checkout] Missing STRIPE_SECRET_KEY");
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
    let body: { church_id?: string; success_url?: string; cancel_url?: string };
    try {
      body = await req.json();
    } catch {
      return NextResponse.json(
        { ok: false, error: "Invalid JSON body" },
        { status: 400 }
      );
    }

    const church_id = body.church_id;
    const success_url = body.success_url;
    const cancel_url = body.cancel_url;

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
      console.error("[Billing Create Subscription Checkout] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, stripe_customer_id")
      .eq("church_id", church_id)
      .single();

    if (churchError) {
      console.error("[Billing Create Subscription Checkout] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // Check if customer exists
    if (!church.stripe_customer_id) {
      return NextResponse.json(
        { ok: false, error: "Church does not have a Stripe customer. Create customer first." },
        { status: 400 }
      );
    }

    // Get or create subscription price
    const priceId = await getOrCreateSubscriptionPrice(stripe);

    // Determine return URLs
    // Get site URL (enforces production URLs)
    let siteUrl: string;
    try {
      siteUrl = getSiteUrl();
    } catch (err: any) {
      return NextResponse.json(
        { ok: false, error: "Site URL not configured" },
        { status: 500 }
      );
    }
    const finalSuccessUrl = success_url || `${siteUrl}/admin/billing?success=true&church_id=${encodeURIComponent(church_id)}`;
    const finalCancelUrl = cancel_url || `${siteUrl}/admin/billing?canceled=true&church_id=${encodeURIComponent(church_id)}`;

    // Create Checkout Session for subscription
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      customer: church.stripe_customer_id,
      line_items: [
        {
          price: priceId,
          quantity: 1,
        },
      ],
      metadata: {
        church_id: church_id,
      },
      success_url: finalSuccessUrl,
      cancel_url: finalCancelUrl,
    });

    return NextResponse.json({
      ok: true,
      url: session.url,
      session_id: session.id,
    });
  } catch (err: any) {
    console.error("[Billing Create Subscription Checkout] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

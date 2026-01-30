import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { checkRateLimit, RATE_LIMITS } from "@/lib/rateLimit";
import { isChurchEligibleForDonations } from "@/lib/churchEligibility";
import { DONATION_PRESETS, isValidPresetAmount, type DonationFrequency } from "@/lib/donationConstants";
import { getOrCreateDonationPrice } from "@/lib/stripePrices";
import { getSiteUrl } from "@/lib/siteUrl";
import { apiError, apiSuccess, ERROR_CODES } from "@/lib/apiResponses";
import { generateRequestId, logRequest, logError } from "@/lib/requestLogger";

export const runtime = "nodejs";

/**
 * POST handler to create Stripe Checkout Session with Connect destination charges
 * 
 * Uses Stripe Connect platform model:
 * - Payments go directly to connected account (church)
 * - Platform (EasyGiveQR) takes 0% application fee (revenue is subscription-only)
 * - Churches pay Stripe processing fees directly
 * 
 * Environment variables required:
 * - STRIPE_SECRET_KEY: Stripe secret key (platform account)
 * - SUPABASE_URL: Supabase project URL
 * - SUPABASE_SERVICE_ROLE_KEY: Supabase service role key
 */
export async function POST(req: Request) {
  const requestId = generateRequestId();
  const route = "/api/checkout-session";

  try {
    logRequest(requestId, route, "POST");

    // Rate limiting
    const rateLimitError = checkRateLimit(req, RATE_LIMITS.checkout.maxRequests, RATE_LIMITS.checkout.windowMs);
    if (rateLimitError) return rateLimitError;

    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
    if (!stripeSecretKey) {
      logError(requestId, route, ERROR_CODES.CONFIGURATION_ERROR, "STRIPE_SECRET_KEY missing");
      return apiError(ERROR_CODES.CONFIGURATION_ERROR, 500, "Server configuration error");
    }

    const stripe = new Stripe(stripeSecretKey, {
      apiVersion: "2025-12-15.clover",
    });

    const body = await req.json().catch(() => ({} as any));

    const amount_cents = Number(body?.amount_cents);
    const church_id = String(body?.church_id || "");
    const frequency = String(body?.frequency || "one_time") as DonationFrequency;

    // Validate church_id format (EGQR-XXX pattern)
    if (!church_id) {
      logError(requestId, route, ERROR_CODES.MISSING_FIELD, "church_id is required");
      return apiError(ERROR_CODES.MISSING_FIELD, 400, "church_id is required");
    }

    // Validate church_id format (must match EGQR-XXX pattern)
    if (!/^EGQR-\d+$/.test(church_id)) {
      logError(requestId, route, ERROR_CODES.INVALID_INPUT, `Invalid church_id format: ${church_id}`);
      return apiError(ERROR_CODES.INVALID_INPUT, 400, "Invalid church ID format.");
    }

    // Validate amount_cents is a valid preset
    if (!amount_cents || Number.isNaN(amount_cents) || !isValidPresetAmount(amount_cents)) {
      logError(requestId, route, ERROR_CODES.INVALID_AMOUNT, `Invalid amount: ${amount_cents}`);
      return apiError(ERROR_CODES.INVALID_AMOUNT, 400, "Invalid donation amount. Please select a preset amount.");
    }

    // Validate frequency
    if (frequency !== "one_time" && frequency !== "monthly") {
      logError(requestId, route, ERROR_CODES.INVALID_FREQUENCY, `Invalid frequency: ${frequency}`);
      return apiError(ERROR_CODES.INVALID_FREQUENCY, 400, "Invalid frequency. Must be 'one_time' or 'monthly'.");
    }

    // Get Supabase admin client to fetch church's Stripe account
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      logError(requestId, route, ERROR_CODES.CONFIGURATION_ERROR, "Failed to initialize Supabase client");
      return apiError(ERROR_CODES.CONFIGURATION_ERROR, 500, "Server configuration error");
    }

    // Check global kill switch first
    const globalKillSwitch = process.env.DONATIONS_PAUSED === "true";
    if (globalKillSwitch) {
      logError(requestId, route, ERROR_CODES.CHURCH_NOT_ACTIVE, "Global donations kill switch is ON");
      return apiError(ERROR_CODES.CHURCH_NOT_ACTIVE, 503, "Donations are temporarily paused. Please try again later.");
    }

    // Fetch church to check eligibility
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select(
        "church_id, status, subscription_status, stripe_account_id, stripe_charges_enabled, stripe_payouts_enabled, monthly_enabled, donations_paused"
      )
      .eq("church_id", church_id)
      .single();

    if (churchError || !church) {
      logError(requestId, route, ERROR_CODES.CHURCH_NOT_FOUND, `Church not found: ${church_id}`);
      return apiError(ERROR_CODES.CHURCH_NOT_FOUND, 404, "Church not found");
    }

    // Additional validation: ensure church exists in database (double-check)
    if (!church.church_id) {
      logError(requestId, route, ERROR_CODES.CHURCH_NOT_FOUND, `Church not found in database: ${church_id}`);
      return apiError(ERROR_CODES.CHURCH_NOT_FOUND, 404, "Church not found");
    }

    // Check eligibility for donations (with admin override if enabled)
    const allowInactiveOverride =
      process.env.ALLOW_DONATIONS_WHEN_INACTIVE === "true" && process.env.NODE_ENV !== "production";

    if (!isChurchEligibleForDonations(church, allowInactiveOverride)) {
      logError(requestId, route, ERROR_CODES.CHURCH_NOT_ACTIVE, `Church not eligible: ${church_id}`, {
        status: church.status,
        subscription_status: church.subscription_status,
      });
      return apiError(ERROR_CODES.CHURCH_NOT_ACTIVE, 403, "This church is not currently accepting donations.");
    }

    // Verify Stripe Connect account exists (should be true if eligible, but double-check)
    if (!church.stripe_account_id) {
      logError(requestId, route, ERROR_CODES.CONFIGURATION_ERROR, `Church missing Stripe account: ${church_id}`);
      return apiError(ERROR_CODES.CONFIGURATION_ERROR, 400, "Church has not completed payment setup.");
    }

    // Check if monthly donations are enabled (if frequency is monthly)
    if (frequency === "monthly" && !church.monthly_enabled) {
      logError(requestId, route, ERROR_CODES.MONTHLY_NOT_ENABLED, `Monthly not enabled: ${church_id}`);
      return apiError(ERROR_CODES.MONTHLY_NOT_ENABLED, 403, "Monthly donations are not enabled for this church.");
    }

    // Best-effort origin/referrer check for browser calls (anti-abuse)
    const origin = req.headers.get("origin");
    const referer = req.headers.get("referer");
    const isBrowserRequest = origin || referer;
    
    // In production, log suspicious requests (no origin/referer) but don't block
    // (API clients may not send these headers)
    if (process.env.NODE_ENV === "production" && !isBrowserRequest) {
      logError(requestId, route, "suspicious_request", "Request without origin/referer", {
        ip: req.headers.get("x-forwarded-for") || "unknown",
      });
      // Don't block - just log for monitoring
    }

    // Get site URL (ensures production uses https://easygiveqr.net)
    const requestOrigin = origin || `http://${req.headers.get("host") || "localhost:3000"}`;
    let siteUrl: string;
    try {
      siteUrl = getSiteUrl(requestOrigin);
    } catch (err: any) {
      logError(requestId, route, ERROR_CODES.CONFIGURATION_ERROR, "Site URL not configured", {
        error: err.message,
      });
      return apiError(ERROR_CODES.CONFIGURATION_ERROR, 500, "Server configuration error");
    }

    // Prepare metadata
    const metadata: Record<string, string> = {
      church_id,
      frequency,
      amount_cents: String(amount_cents),
    };

    // Create checkout session based on frequency
    let session: Stripe.Checkout.Session;

    if (frequency === "monthly") {
      // Monthly recurring donation - use subscription mode
      const priceId = await getOrCreateDonationPrice(stripe, amount_cents, "monthly");

      if (!priceId) {
        logError(requestId, route, ERROR_CODES.SERVER_ERROR, "Failed to create subscription price");
        return apiError(ERROR_CODES.SERVER_ERROR, 500, "Failed to create subscription");
      }

      // For subscriptions with Connect, we create the subscription on the platform account
      // Note: Full Connect destination charges for subscriptions require creating the subscription
      // on the connected account, which is more complex. For v1, we create on platform and
      // can enhance Connect integration later if needed.
      session = await stripe.checkout.sessions.create({
        mode: "subscription",
        payment_method_types: ["card"],
        line_items: [
          {
            price: priceId,
            quantity: 1,
          },
        ],

        // Metadata for reconciliation
        metadata,

        // Subscription metadata
        subscription_data: {
          metadata,
        },

        // Return URLs
        success_url: `${siteUrl}/donate/success?church_id=${encodeURIComponent(
          church_id
        )}&session_id={CHECKOUT_SESSION_ID}`,
        cancel_url: `${siteUrl}/donate/cancel?church_id=${encodeURIComponent(church_id)}`,
      });
    } else {
      // One-time donation - use payment mode
      session = await stripe.checkout.sessions.create({
        mode: "payment",
        payment_method_types: ["card"],
        line_items: [
          {
            price_data: {
              currency: "usd",
              product_data: { name: "Donation" },
              unit_amount: amount_cents,
            },
            quantity: 1,
          },
        ],

        // Stripe Connect: destination charges
        // Funds go directly to connected account (church)
        // Platform takes 0% application fee (revenue is subscription-only)
        // Churches pay Stripe processing fees directly
        payment_intent_data: {
          transfer_data: {
            destination: church.stripe_account_id,
          },
          // application_fee_amount: 0 (default, no platform fee)
        },

        // Metadata for reconciliation
        metadata,

        // Return URLs
        success_url: `${siteUrl}/donate/success?church_id=${encodeURIComponent(
          church_id
        )}&session_id={CHECKOUT_SESSION_ID}`,
        cancel_url: `${siteUrl}/donate/cancel?church_id=${encodeURIComponent(church_id)}`,
      });
    }

    return apiSuccess({ url: session.url });
  } catch (err: any) {
    logError(requestId, route, ERROR_CODES.SERVER_ERROR, err?.message || "Unknown error");
    return apiError(ERROR_CODES.SERVER_ERROR, 500, "An error occurred. Please try again.");
  }
}

import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";
import { getDonationUrl } from "@/lib/siteUrl";
import { getSiteUrl } from "@/lib/siteUrl";

export const runtime = "nodejs";

/**
 * POST handler to generate church launch pack
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123"
 * }
 * 
 * Protected by x-admin-secret
 * Returns all URLs and information needed for church launch
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));

    const church_id = String(body?.church_id || "");

    // Validate church_id
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
      console.error("[Church Pack] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church data
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select(
        "church_id, display_name, logo_url, qr_code_url, stripe_account_id, stripe_onboarding_status"
      )
      .eq("church_id", church_id)
      .single();

    if (churchError || !church) {
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // Get site URL for generating links
    let siteUrl: string;
    try {
      siteUrl = getSiteUrl();
    } catch (err: any) {
      console.error("[Church Pack] Site URL not configured");
      return NextResponse.json(
        { ok: false, error: "Site URL not configured" },
        { status: 500 }
      );
    }

    // Generate URLs
    const donateUrl = getDonationUrl(church_id);
    const prayerUrl = `${siteUrl}/engage/prayer?church_id=${encodeURIComponent(church_id)}`;
    const visitorUrl = `${siteUrl}/engage/visitor?church_id=${encodeURIComponent(church_id)}`;
    const volunteerUrl = `${siteUrl}/engage/volunteer?church_id=${encodeURIComponent(church_id)}`;

    // Get Stripe onboarding link if needed
    let stripeOnboardingUrl: string | null = null;
    if (church.stripe_account_id && church.stripe_onboarding_status !== "complete") {
      // Try to generate onboarding link
      try {
        const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
        if (stripeSecretKey) {
          const Stripe = require("stripe").default;
          const stripe = new Stripe(stripeSecretKey, {
            apiVersion: "2025-12-15.clover",
          });

          const returnUrl = `${siteUrl}/admin/onboarding/complete?church_id=${encodeURIComponent(church_id)}`;
          const refreshUrl = `${siteUrl}/admin/onboarding?church_id=${encodeURIComponent(church_id)}`;

          const accountLink = await stripe.accountLinks.create({
            account: church.stripe_account_id,
            refresh_url: refreshUrl,
            return_url: returnUrl,
            type: "account_onboarding",
          });

          stripeOnboardingUrl = accountLink.url;
        }
      } catch (err: any) {
        console.error("[Church Pack] Failed to generate onboarding link", err);
        // Continue without onboarding URL
      }
    }

    return NextResponse.json({
      ok: true,
      church_id: church.church_id,
      display_name: church.display_name,
      donate_url: donateUrl,
      qr_code_url: church.qr_code_url || null,
      logo_url: church.logo_url || null,
      engage: {
        prayer: prayerUrl,
        visitor: visitorUrl,
        volunteer: volunteerUrl,
      },
      stripe: {
        account_id: church.stripe_account_id || null,
        onboarding_status: church.stripe_onboarding_status || null,
        onboarding_url: stripeOnboardingUrl,
      },
    });
  } catch (err: any) {
    console.error("[Church Pack] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

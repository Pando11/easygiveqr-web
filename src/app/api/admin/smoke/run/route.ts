import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";
import { getSiteUrl } from "@/lib/siteUrl";

export const runtime = "nodejs";

/**
 * POST handler for smoke test (read-only health checks)
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123" (optional)
 * }
 * 
 * Protected by x-admin-secret
 * Performs read-only checks and returns PASS/FAIL
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));
    const church_id = String(body?.church_id || "");

    const checks: Array<{ name: string; status: "pass" | "fail"; message?: string }> = [];

    // Check 1: Environment variables
    const requiredEnvVars = [
      "SUPABASE_URL",
      "SUPABASE_SERVICE_ROLE_KEY",
      "STRIPE_SECRET_KEY",
      "STRIPE_WEBHOOK_SECRET",
      "SENDGRID_API_KEY",
      "SENDGRID_FROM_EMAIL",
    ];
    const missingEnvVars = requiredEnvVars.filter((varName) => !process.env[varName]);
    if (missingEnvVars.length === 0) {
      checks.push({ name: "Environment Variables", status: "pass" });
    } else {
      checks.push({
        name: "Environment Variables",
        status: "fail",
        message: `Missing: ${missingEnvVars.join(", ")}`,
      });
    }

    // Check 2: Site URL configured
    try {
      const siteUrl = getSiteUrl();
      checks.push({ name: "Site URL", status: "pass", message: siteUrl });
    } catch (err: any) {
      checks.push({ name: "Site URL", status: "fail", message: err.message });
    }

    // Check 3: Supabase connectivity
    try {
      const supabase = getSupabaseAdmin();
      const { error } = await supabase.from("churches").select("church_id").limit(1);
      if (!error) {
        checks.push({ name: "Supabase Connectivity", status: "pass" });
      } else {
        checks.push({ name: "Supabase Connectivity", status: "fail", message: error.message });
      }
    } catch (err: any) {
      checks.push({ name: "Supabase Connectivity", status: "fail", message: err.message });
    }

    // Check 4: Can query donations table
    try {
      const supabase = getSupabaseAdmin();
      const { error } = await supabase.from("donations").select("id").limit(1);
      if (!error) {
        checks.push({ name: "Donations Table Access", status: "pass" });
      } else {
        checks.push({ name: "Donations Table Access", status: "fail", message: error.message });
      }
    } catch (err: any) {
      checks.push({ name: "Donations Table Access", status: "fail", message: err.message });
    }

    // Check 5: Webhook endpoint reachable
    try {
      const siteUrl = getSiteUrl();
      const webhookUrl = `${siteUrl}/api/stripe-webhook`;
      const response = await fetch(webhookUrl, { method: "GET" });
      if (response.ok) {
        checks.push({ name: "Webhook Endpoint", status: "pass", message: webhookUrl });
      } else {
        checks.push({
          name: "Webhook Endpoint",
          status: "fail",
          message: `HTTP ${response.status}`,
        });
      }
    } catch (err: any) {
      checks.push({ name: "Webhook Endpoint", status: "fail", message: err.message });
    }

    // Check 6: Church exists and eligible (if church_id provided)
    if (church_id) {
      try {
        const supabase = getSupabaseAdmin();
        const { data: church, error } = await supabase
          .from("churches")
          .select("church_id, status, subscription_status, donations_paused")
          .eq("church_id", church_id)
          .single();

        if (!error && church) {
          const isEligible =
            church.status === "active" &&
            church.subscription_status === "active" &&
            !church.donations_paused;
          checks.push({
            name: "Church Eligibility",
            status: isEligible ? "pass" : "fail",
            message: isEligible
              ? "Church is eligible for donations"
              : `Status: ${church.status}, Subscription: ${church.subscription_status}, Paused: ${church.donations_paused}`,
          });
        } else {
          checks.push({ name: "Church Eligibility", status: "fail", message: "Church not found" });
        }
      } catch (err: any) {
        checks.push({ name: "Church Eligibility", status: "fail", message: err.message });
      }
    }

    // Calculate overall status
    const allPassed = checks.every((c) => c.status === "pass");
    const overallStatus = allPassed ? "PASS" : "FAIL";

    return NextResponse.json({
      ok: true,
      status: overallStatus,
      checks,
      timestamp: new Date().toISOString(),
    });
  } catch (err: any) {
    console.error("[Smoke Test] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error", message: err?.message },
      { status: 500 }
    );
  }
}

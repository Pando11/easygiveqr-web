import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { checkRateLimit, RATE_LIMITS } from "@/lib/rateLimit";
import { apiError, apiSuccess, ERROR_CODES } from "@/lib/apiResponses";
import { generateRequestId, logRequest, logError } from "@/lib/requestLogger";

export const runtime = "nodejs";

/**
 * GET handler to lookup donation by Stripe session ID
 * 
 * Query parameters:
 * - session_id: Stripe checkout session ID (required)
 * 
 * Returns:
 * - 200: { ok: true, donation: {...} } if found
 * - 404: { ok: false, error: "not_found" } if not found
 * - 400: { ok: false, error: "Missing session_id" } if session_id missing
 */
export async function GET(req: Request) {
  const requestId = generateRequestId();
  const route = "/api/donation";

  try {
    logRequest(requestId, route, "GET");

    // Rate limiting
    const rateLimitError = checkRateLimit(req, RATE_LIMITS.donation.maxRequests, RATE_LIMITS.donation.windowMs);
    if (rateLimitError) return rateLimitError;

    // Get session_id from query parameters
    const { searchParams } = new URL(req.url);
    const session_id = searchParams.get("session_id");

    // Validate session_id is present
    if (!session_id) {
      logError(requestId, route, ERROR_CODES.MISSING_FIELD, "session_id is required");
      return apiError(ERROR_CODES.MISSING_FIELD, 400, "session_id is required");
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      logError(requestId, route, ERROR_CODES.CONFIGURATION_ERROR, "Failed to initialize Supabase client");
      return apiError(ERROR_CODES.CONFIGURATION_ERROR, 500, "Server configuration error");
    }

    // Query donation by stripe_session_id
    const { data, error } = await supabase
      .from("donations")
      .select("*")
      .eq("stripe_session_id", session_id)
      .single();

    if (error) {
      // If no rows found, return 404
      if (error.code === "PGRST116") {
        return apiError(ERROR_CODES.DONATION_NOT_FOUND, 404);
      }

      logError(requestId, route, ERROR_CODES.DATABASE_ERROR, "Supabase query failed", {
        error: error.message,
      });
      return apiError(ERROR_CODES.DATABASE_ERROR, 500, "Database error");
    }

    // Return donation data
    return apiSuccess({
      donation: {
        church_id: data.church_id,
        stripe_session_id: data.stripe_session_id,
        amount_cents: data.amount_cents,
        currency: data.currency,
        status: data.status,
        created_at: data.created_at,
      },
    });
  } catch (err: any) {
    logError(requestId, route, ERROR_CODES.SERVER_ERROR, err?.message || "Unknown error");
    return apiError(ERROR_CODES.SERVER_ERROR, 500, "An error occurred. Please try again.");
  }
}

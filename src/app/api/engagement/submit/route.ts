import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { getEngagementTranslations, type EngagementType } from "@/lib/engagementTranslations";
import {
  generateEngagementEmailSubject,
  generateEngagementEmailHtml,
  generateEngagementEmailText,
} from "@/lib/engagementEmailTemplates";
import { sendEmail } from "@/lib/email/sendEmail";
import { apiError, apiSuccess, ERROR_CODES } from "@/lib/apiResponses";
import { generateRequestId, logRequest, logError } from "@/lib/requestLogger";
import { checkRateLimit, RATE_LIMITS } from "@/lib/rateLimit";

export const runtime = "nodejs";

/**
 * POST handler to submit an engagement form (prayer, visitor, volunteer)
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123",
 *   "type": "prayer" | "visitor" | "volunteer",
 *   "name": "John Doe" (optional for prayer, required for visitor/volunteer),
 *   "email": "john@example.com" (optional),
 *   "phone": "+1234567890" (optional),
 *   "message": "Prayer request text" (required for prayer, optional for others),
 *   "meta": {} (optional, JSON object for extra fields)
 * }
 */
export async function POST(req: Request) {
  const requestId = generateRequestId();
  const route = "/api/engagement/submit";

  try {
    logRequest(requestId, route, "POST");

    // Rate limiting (hardened)
    const rateLimitError = checkRateLimit(req, RATE_LIMITS.engagement.maxRequests, RATE_LIMITS.engagement.windowMs);
    if (rateLimitError) return rateLimitError;

    const body = await req.json().catch(() => ({} as any));

    const church_id = String(body?.church_id || "");
    const type = String(body?.type || "") as EngagementType;
    const name = body?.name ? String(body.name).trim() : null;
    const email = body?.email ? String(body.email).trim() : null;
    const phone = body?.phone ? String(body.phone).trim() : null;
    const message = body?.message ? String(body.message).trim() : null;
    const meta = body?.meta || null;

    // Validate church_id
    if (!church_id) {
      logError(requestId, route, ERROR_CODES.MISSING_FIELD, "church_id is required");
      return apiError(ERROR_CODES.MISSING_FIELD, 400, "church_id is required");
    }

    // Validate type
    if (!type || !["prayer", "visitor", "volunteer"].includes(type)) {
      logError(requestId, route, ERROR_CODES.INVALID_INPUT, `Invalid type: ${type}`);
      return apiError(ERROR_CODES.INVALID_INPUT, 400, "Invalid type. Must be 'prayer', 'visitor', or 'volunteer'.");
    }

    // Validate required fields based on type
    if (type === "prayer") {
      if (!message || message.length === 0) {
        logError(requestId, route, ERROR_CODES.MISSING_FIELD, "Message required for prayer");
        return apiError(ERROR_CODES.MISSING_FIELD, 400, "Message is required for prayer requests.");
      }
    } else if (type === "visitor" || type === "volunteer") {
      if (!name || name.length === 0) {
        logError(requestId, route, ERROR_CODES.MISSING_FIELD, "Name required for visitor/volunteer");
        return apiError(ERROR_CODES.MISSING_FIELD, 400, "Name is required for visitor and volunteer submissions.");
      }
    }

    // Validate email format if provided
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      logError(requestId, route, ERROR_CODES.INVALID_INPUT, "Invalid email format");
      return apiError(ERROR_CODES.INVALID_INPUT, 400, "Invalid email format.");
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      logError(requestId, route, ERROR_CODES.CONFIGURATION_ERROR, "Failed to initialize Supabase client");
      return apiError(ERROR_CODES.CONFIGURATION_ERROR, 500, "Server configuration error");
    }

    // Verify church exists and get church info for email
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, display_name, admin_emails, preferred_language")
      .eq("church_id", church_id)
      .single();

    if (churchError || !church) {
      logError(requestId, route, ERROR_CODES.CHURCH_NOT_FOUND, `Church not found: ${church_id}`);
      return apiError(ERROR_CODES.CHURCH_NOT_FOUND, 404, "Church not found");
    }

    // Insert submission
    const { data: submission, error: insertError } = await supabase
      .from("engagement_submissions")
      .insert({
        church_id,
        type,
        name,
        email,
        phone,
        message,
        meta,
        status: "open",
      })
      .select("id")
      .single();

    if (insertError) {
      logError(requestId, route, ERROR_CODES.DATABASE_ERROR, "Failed to insert submission", {
        error: insertError.message,
      });
      return apiError(ERROR_CODES.DATABASE_ERROR, 500, "Failed to save submission. Please try again.");
    }

    // Send email notification to church admins (if SendGrid is configured)
    // Do not block submission if email fails
    if (church.admin_emails && church.admin_emails.length > 0) {
      const language = (church.preferred_language || "EN") as "EN" | "ES";
      
      const emailData = {
        churchName: church.display_name,
        type,
        name: name || undefined,
        email: email || undefined,
        phone: phone || undefined,
        message: message || undefined,
        meta: meta || undefined,
      };

      const subject = generateEngagementEmailSubject(emailData, language);
      const html = generateEngagementEmailHtml(emailData, language);
      const text = generateEngagementEmailText(emailData, language);

      // Send to all admin emails
      for (const adminEmail of church.admin_emails) {
        try {
          const emailResult = await sendEmail({
            to: adminEmail,
            subject,
            html,
            text,
          });
          if (!emailResult.success) {
            console.error("[Engagement Submit] Failed to send email notification", {
              to: adminEmail,
              error: emailResult.error,
            });
            // Continue - don't block submission
          }
        } catch (emailErr: any) {
          console.error("[Engagement Submit] Email error", {
            to: adminEmail,
            error: emailErr?.message,
          });
          // Continue - don't block submission
        }
      }
    }

    return apiSuccess({ id: submission.id });
  } catch (err: any) {
    logError(requestId, route, ERROR_CODES.SERVER_ERROR, err?.message || "Unknown error");
    return apiError(ERROR_CODES.SERVER_ERROR, 500, "An error occurred. Please try again.");
  }
}

import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";
import {
  generateQRCode,
  createStripeConnectAccount,
  generateStripeOnboardingLink,
  uploadLogo,
} from "@/lib/onboardingHelpers";
import { getDonationUrl } from "@/lib/siteUrl";
import { sendEmail } from "@/lib/email/sendEmail";
import {
  generateOnboardingEmailSubject,
  generateOnboardingEmailHtml,
  generateOnboardingEmailText,
} from "@/lib/onboardingEmailTemplates";
import { getSiteUrl } from "@/lib/siteUrl";
import { validateAndNormalizeEmails } from "@/lib/emailValidation";

export const runtime = "nodejs";

/**
 * Validate church_id format (EGQR-XXX)
 */
function validateChurchId(churchId: string): boolean {
  return /^EGQR-[A-Z0-9]+$/.test(churchId);
}

/**
 * Validate color hex format (#RRGGBB)
 */
function validateColor(color: string): boolean {
  return /^#[0-9A-Fa-f]{6}$/.test(color);
}

/**
 * Validate email format
 */
function validateEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// Note: parseAdminEmails replaced by validateAndNormalizeEmails from emailValidation.ts

/**
 * Get file extension from filename or content type
 */
function getFileExtension(filename: string, contentType: string): string {
  // Try to get from filename first
  const match = filename.match(/\.([^.]+)$/);
  if (match) {
    return match[1].toLowerCase();
  }

  // Fallback to content type
  if (contentType.includes("png")) return "png";
  if (contentType.includes("jpeg") || contentType.includes("jpg")) return "jpg";
  if (contentType.includes("svg")) return "svg";
  if (contentType.includes("webp")) return "webp";

  return "png"; // Default
}

/**
 * POST handler to create a church and provision everything needed
 * 
 * Accepts multipart/form-data with:
 * - church_id (required)
 * - legal_name (required)
 * - display_name (required)
 * - ein (required)
 * - preferred_language (required, EN or ES)
 * - primary_color (required, #RRGGBB)
 * - donation_phrase (required)
 * - admin_emails (required, comma-separated)
 * - logo (required, file)
 * 
 * Automatically provisions:
 * - Logo upload to Supabase Storage
 * - QR code generation
 * - Stripe Connect account creation
 * - Stripe onboarding link generation
 * 
 * Environment variables required:
 * - NEXT_PUBLIC_SITE_URL or SITE_URL: Base URL for donation links
 * - STRIPE_SECRET_KEY: Stripe secret key (platform account)
 * - SUPABASE_URL: Supabase project URL
 * - SUPABASE_SERVICE_ROLE_KEY: Supabase service role key
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    // Parse multipart/form-data
    const formData = await req.formData();

    // Extract form fields
    const church_id = formData.get("church_id")?.toString() || "";
    const legal_name = formData.get("legal_name")?.toString() || "";
    const display_name = formData.get("display_name")?.toString() || "";
    const ein = formData.get("ein")?.toString() || "";
    const preferred_language = formData.get("preferred_language")?.toString() || "";
    const primary_color = formData.get("primary_color")?.toString() || "";
    const donation_phrase = formData.get("donation_phrase")?.toString() || "";
    const admin_emails_string = formData.get("admin_emails")?.toString() || "";
    const monthly_enabled_string = formData.get("monthly_enabled")?.toString() || "false";
    const logo = formData.get("logo") as File | null;

    // Validate required fields
    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    if (!validateChurchId(church_id)) {
      return NextResponse.json(
        { ok: false, error: "Invalid church_id format. Must be EGQR-XXX" },
        { status: 400 }
      );
    }

    if (!legal_name || legal_name.trim().length === 0) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: legal_name" },
        { status: 400 }
      );
    }

    if (!display_name || display_name.trim().length === 0) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: display_name" },
        { status: 400 }
      );
    }

    if (!ein || ein.trim().length === 0) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: ein" },
        { status: 400 }
      );
    }

    if (!preferred_language || !["EN", "ES"].includes(preferred_language.toUpperCase())) {
      return NextResponse.json(
        { ok: false, error: "Missing or invalid preferred_language. Must be EN or ES" },
        { status: 400 }
      );
    }

    if (!primary_color || !validateColor(primary_color)) {
      return NextResponse.json(
        { ok: false, error: "Missing or invalid primary_color. Must be #RRGGBB format" },
        { status: 400 }
      );
    }

    if (!donation_phrase || donation_phrase.trim().length === 0) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: donation_phrase" },
        { status: 400 }
      );
    }

    if (!admin_emails_string || admin_emails_string.trim().length === 0) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: admin_emails" },
        { status: 400 }
      );
    }

    if (!logo) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: logo" },
        { status: 400 }
      );
    }

    // Parse and validate admin emails
    const admin_emails = validateAndNormalizeEmails(admin_emails_string);
    if (admin_emails.length === 0) {
      return NextResponse.json(
        { ok: false, error: "No valid admin emails provided" },
        { status: 400 }
      );
    }

    // Parse monthly_enabled (default to false)
    const monthly_enabled = monthly_enabled_string.toLowerCase() === "true" || monthly_enabled_string === "1";

    // Validate logo file
    const logoSize = logo.size;
    const maxSize = 5 * 1024 * 1024; // 5MB
    if (logoSize > maxSize) {
      return NextResponse.json(
        { ok: false, error: "Logo file too large. Maximum size is 5MB" },
        { status: 400 }
      );
    }

    const logoContentType = logo.type || "image/png";
    if (!logoContentType.startsWith("image/")) {
      return NextResponse.json(
        { ok: false, error: "Logo must be an image file" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Onboarding] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Check if church already exists
    const { data: existingChurch } = await supabase
      .from("churches")
      .select("church_id")
      .eq("church_id", church_id)
      .single();

    if (existingChurch) {
      return NextResponse.json(
        { ok: false, error: "Church with this church_id already exists" },
        { status: 400 }
      );
    }

    // Convert logo file to buffer
    const logoArrayBuffer = await logo.arrayBuffer();
    const logoBuffer = Buffer.from(logoArrayBuffer);
    const logoExtension = getFileExtension(logo.name, logoContentType);

    // Step 1: Upload logo
    const logoResult = await uploadLogo(church_id, logoBuffer, logoExtension, logoContentType);
    if (logoResult.error) {
      return NextResponse.json(
        { ok: false, error: `Failed to upload logo: ${logoResult.error}` },
        { status: 500 }
      );
    }

    // Step 2: Create Stripe Connect account
    const stripeAccountResult = await createStripeConnectAccount(church_id, legal_name);
    if (stripeAccountResult.error) {
      return NextResponse.json(
        { ok: false, error: `Failed to create Stripe account: ${stripeAccountResult.error}` },
        { status: 500 }
      );
    }

    // Step 3: Generate QR code
    const qrResult = await generateQRCode(church_id);
    if (qrResult.error) {
      // QR generation failure is not critical, continue without it
      console.warn("[Onboarding] QR code generation failed", qrResult.error);
    }

    // Step 4: Insert church into database
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
    const returnUrl = `${siteUrl}/admin/onboarding/complete?church_id=${encodeURIComponent(church_id)}`;
    const refreshUrl = `${siteUrl}/admin/onboarding?church_id=${encodeURIComponent(church_id)}`;

    const { error: insertError } = await supabase.from("churches").insert({
      church_id: church_id.trim(),
      legal_name: legal_name.trim(),
      display_name: display_name.trim(),
      ein: ein.trim(),
      preferred_language: preferred_language.toUpperCase(),
      primary_color: primary_color,
      donation_phrase: donation_phrase.trim(),
      admin_emails: admin_emails,
      monthly_enabled: monthly_enabled,
      logo_url: logoResult.url,
      stripe_account_id: stripeAccountResult.accountId,
      stripe_onboarding_status: "not_started",
      stripe_charges_enabled: false,
      stripe_payouts_enabled: false,
      stripe_details_submitted: false,
      qr_code_url: qrResult.url || null,
      qr_code_updated_at: qrResult.url ? new Date().toISOString() : null,
      status: "pending",
    });

    if (insertError) {
      console.error("[Onboarding] Failed to insert church", {
        error: insertError.message,
      });
      return NextResponse.json(
        { ok: false, error: `Database error: ${insertError.message}` },
        { status: 500 }
      );
    }

    // Step 5: Generate Stripe onboarding link
    const onboardingLinkResult = await generateStripeOnboardingLink(
      stripeAccountResult.accountId,
      returnUrl,
      refreshUrl
    );

    if (onboardingLinkResult.error) {
      console.warn("[Onboarding] Failed to generate onboarding link", onboardingLinkResult.error);
    }

    // Update onboarding status if link was generated
    if (onboardingLinkResult.url) {
      await supabase
        .from("churches")
        .update({ stripe_onboarding_status: "pending" })
        .eq("church_id", church_id);
    }

    const donateUrl = getDonationUrl(church_id);

    // Reuse siteUrl for engagement links (already set above)

    const prayerUrl = `${siteUrl}/engage/prayer?church_id=${encodeURIComponent(church_id)}`;
    const visitorUrl = `${siteUrl}/engage/visitor?church_id=${encodeURIComponent(church_id)}`;
    const volunteerUrl = `${siteUrl}/engage/volunteer?church_id=${encodeURIComponent(church_id)}`;

    // Send onboarding completion email to church admins (optional, don't block on failure)
    if (admin_emails && admin_emails.length > 0) {
      try {
        const language = (preferred_language.toUpperCase() || "EN") as "EN" | "ES";
        const emailData = {
          churchName: display_name.trim(),
          donateUrl,
          qrCodeUrl: qrResult.url || null,
          logoUrl: logoResult.url || null,
          prayerUrl,
          visitorUrl,
          volunteerUrl,
          stripeOnboardingUrl: onboardingLinkResult.url || null,
          stripeOnboardingStatus: onboardingLinkResult.url ? "pending" : null,
        };

        const subject = generateOnboardingEmailSubject(emailData, language);
        const html = generateOnboardingEmailHtml(emailData, language);
        const text = generateOnboardingEmailText(emailData, language);

        // Send to all admin emails
        for (const adminEmail of admin_emails) {
          try {
            const emailResult = await sendEmail({
              to: adminEmail,
              subject,
              html,
              text,
            });
            if (!emailResult.success) {
              console.warn("[Onboarding] Failed to send onboarding email", {
                to: adminEmail,
                error: emailResult.error,
              });
              // Continue - don't block onboarding
            }
          } catch (emailErr: any) {
            console.warn("[Onboarding] Email error", {
              to: adminEmail,
              error: emailErr?.message,
            });
            // Continue - don't block onboarding
          }
        }
      } catch (emailErr: any) {
        console.warn("[Onboarding] Failed to send onboarding email", emailErr);
        // Continue - don't block onboarding
      }
    }

    return NextResponse.json({
      ok: true,
      church_id,
      donate_url: donateUrl,
      logo_url: logoResult.url,
      qr_code_url: qrResult.url || null,
      stripe_account_id: stripeAccountResult.accountId,
      onboarding_link: onboardingLinkResult.url || null,
    });
  } catch (err: any) {
    console.error("[Onboarding] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

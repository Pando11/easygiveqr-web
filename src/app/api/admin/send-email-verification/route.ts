import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";
import { sendEmail } from "@/lib/email/sendEmail";
import { getSiteUrl } from "@/lib/siteUrl";
import { randomUUID } from "crypto";

export const runtime = "nodejs";

/**
 * POST handler to send email verification emails to church admins
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123"
 * }
 * 
 * Protected by x-admin-secret
 * Sends verification email to each admin email with a unique token
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));
    const church_id = String(body?.church_id || "");

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
      console.error("[Email Verification] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, display_name, admin_emails")
      .eq("church_id", church_id)
      .single();

    if (churchError || !church) {
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    if (!church.admin_emails || church.admin_emails.length === 0) {
      return NextResponse.json(
        { ok: false, error: "Church has no admin emails configured" },
        { status: 400 }
      );
    }

    // Get site URL
    let siteUrl: string;
    try {
      siteUrl = getSiteUrl();
    } catch (err: any) {
      return NextResponse.json(
        { ok: false, error: "Site URL not configured" },
        { status: 500 }
      );
    }

    // Generate verification tokens and send emails
    const results: Array<{ email: string; success: boolean; error?: string }> = [];

    for (const email of church.admin_emails) {
      try {
        // Generate unique token
        const token = randomUUID();

        // Create or update verification record
        const { error: upsertError } = await supabase
          .from("email_verifications")
          .upsert(
            {
              church_id,
              email,
              token,
              status: "pending",
              created_at: new Date().toISOString(),
            },
            {
              onConflict: "church_id,email",
            }
          );

        if (upsertError) {
          results.push({ email, success: false, error: upsertError.message });
          continue;
        }

        // Generate verification URL
        const verifyUrl = `${siteUrl}/admin/verify-email?church_id=${encodeURIComponent(
          church_id
        )}&email=${encodeURIComponent(email)}&token=${encodeURIComponent(token)}`;

        // Send verification email
        const subject = `Verify your email for ${church.display_name}`;
        const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .button { display: inline-block; padding: 12px 24px; background: #1D4ED8; color: white; text-decoration: none; border-radius: 6px; margin: 16px 0; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Verify Your Email</h1>
    <p>Hello,</p>
    <p>Please verify your email address for <strong>${church.display_name}</strong> by clicking the button below:</p>
    <p><a href="${verifyUrl}" class="button">Verify Email</a></p>
    <p>Or copy and paste this link into your browser:</p>
    <p style="word-break: break-all; color: #666; font-size: 12px;">${verifyUrl}</p>
    <p>This link will expire in 7 days.</p>
    <p>If you did not request this verification, please ignore this email.</p>
  </div>
</body>
</html>
        `.trim();

        const text = `
Verify Your Email

Hello,

Please verify your email address for ${church.display_name} by visiting:

${verifyUrl}

This link will expire in 7 days.

If you did not request this verification, please ignore this email.
        `.trim();

        const emailResult = await sendEmail({
          to: email,
          subject,
          html,
          text,
        });

        if (emailResult.success) {
          results.push({ email, success: true });
        } else {
          results.push({ email, success: false, error: emailResult.error });
        }
      } catch (err: any) {
        results.push({ email, success: false, error: err?.message || "Unknown error" });
      }
    }

    const successCount = results.filter((r) => r.success).length;
    const failCount = results.filter((r) => !r.success).length;

    return NextResponse.json({
      ok: true,
      church_id,
      sent: successCount,
      failed: failCount,
      results,
    });
  } catch (err: any) {
    console.error("[Email Verification] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

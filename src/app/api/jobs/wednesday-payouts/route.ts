import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireCronSecret } from "@/lib/requireAdmin";
import { logJobRun } from "@/lib/jobLogger";
import { getLastWednesday, getThisWednesday, formatDateRange } from "@/lib/dateUtils";

export const runtime = "nodejs";

interface Church {
  church_id: string;
  display_name: string;
  legal_name: string;
  stripe_account_id: string | null;
  stripe_charges_enabled: boolean;
  stripe_payouts_enabled: boolean;
  stripe_onboarding_status: string;
  admin_emails: string[];
  preferred_language: "EN" | "ES";
}

/**
 * Send email via SendGrid
 */
async function sendEmail(
  to: string,
  subject: string,
  html: string,
  text: string
): Promise<{ success: boolean; error?: string }> {
  const apiKey = process.env.SENDGRID_API_KEY;
  const fromEmail = process.env.SENDGRID_FROM_EMAIL;

  if (!apiKey) {
    return { success: false, error: "SENDGRID_API_KEY not configured" };
  }

  if (!fromEmail) {
    return { success: false, error: "SENDGRID_FROM_EMAIL not configured" };
  }

  try {
    const response = await fetch("https://api.sendgrid.com/v3/mail/send", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        personalizations: [
          {
            to: [{ email: to }],
          },
        ],
        from: { email: fromEmail },
        subject,
        content: [
          { type: "text/plain", value: text },
          { type: "text/html", value: html },
        ],
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      return { success: false, error: `SendGrid error: ${response.status} ${errorText}` };
    }

    return { success: true };
  } catch (err: any) {
    return { success: false, error: err?.message || "Unknown error" };
  }
}

/**
 * Generate deposit status email
 */
function generateDepositStatusEmail(
  church: Church,
  weekStart: string,
  weekEnd: string,
  weeklyTotal: number,
  weeklyTotalFormatted: string,
  payoutStatus: string,
  language: "EN" | "ES"
): { subject: string; html: string; text: string } {
  const churchName = church.display_name || church.legal_name || church.church_id;

  if (language === "ES") {
    const subject = `${churchName} — Estado de Depósito Semanal`;

    const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
    .status-box { background: #f9f9f9; padding: 15px; border-radius: 6px; margin: 15px 0; }
    .total { font-size: 24px; font-weight: bold; color: #1D4ED8; margin: 10px 0; }
    .status { font-size: 18px; font-weight: bold; margin: 10px 0; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Estado de Depósito Semanal</h1>
      <p><strong>${churchName}</strong></p>
    </div>

    <p>Período: ${weekStart} a ${weekEnd}</p>

    <div class="status-box">
      <h2>Total de la Semana</h2>
      <div class="total">${weeklyTotalFormatted}</div>
    </div>

    <div class="status-box">
      <h2>Estado del Depósito</h2>
      <div class="status">${payoutStatus}</div>
    </div>

    <div class="footer">
      <p>Este es un resumen automatizado. Los fondos se procesan directamente a través de Stripe Connect.</p>
    </div>
  </div>
</body>
</html>
    `.trim();

    const text = `
Estado de Depósito Semanal
${churchName}

Período: ${weekStart} a ${weekEnd}

Total de la Semana: ${weeklyTotalFormatted}

Estado del Depósito: ${payoutStatus}

Este es un resumen automatizado. Los fondos se procesan directamente a través de Stripe Connect.
    `.trim();

    return { subject, html, text };
  }

  // English
  const subject = `${churchName} — Weekly Deposit Status`;

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
    .status-box { background: #f9f9f9; padding: 15px; border-radius: 6px; margin: 15px 0; }
    .total { font-size: 24px; font-weight: bold; color: #1D4ED8; margin: 10px 0; }
    .status { font-size: 18px; font-weight: bold; margin: 10px 0; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Weekly Deposit Status</h1>
      <p><strong>${churchName}</strong></p>
    </div>

    <p>Period: ${weekStart} to ${weekEnd}</p>

    <div class="status-box">
      <h2>Weekly Total</h2>
      <div class="total">${weeklyTotalFormatted}</div>
    </div>

    <div class="status-box">
      <h2>Deposit Status</h2>
      <div class="status">${payoutStatus}</div>
    </div>

    <div class="footer">
      <p>This is an automated summary. Funds are processed directly through Stripe Connect.</p>
    </div>
  </div>
</body>
</html>
  `.trim();

  const text = `
Weekly Deposit Status
${churchName}

Period: ${weekStart} to ${weekEnd}

Weekly Total: ${weeklyTotalFormatted}

Deposit Status: ${payoutStatus}

This is an automated summary. Funds are processed directly through Stripe Connect.
  `.trim();

  return { subject, html, text };
}

/**
 * Format currency amount from cents
 */
function formatCurrency(cents: number, currency: string = "usd"): string {
  const amount = cents / 100;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(amount);
}

/**
 * POST handler for Wednesday payout reconciliation job
 * 
 * Secured with x-cron-secret header
 * 
 * For v1: Generates reconciliation email only
 * Relies on Stripe's automatic payout schedule for connected accounts
 * 
 * Environment variables required:
 * - CRON_SECRET: Secret for authenticating cron requests
 * - STRIPE_SECRET_KEY: Stripe secret key (platform account)
 * - SENDGRID_API_KEY: SendGrid API key
 * - SENDGRID_FROM_EMAIL: From email address
 * - SUPABASE_URL: Supabase project URL
 * - SUPABASE_SERVICE_ROLE_KEY: Supabase service role key
 */
export async function POST(req: Request) {
  try {
    // Verify cron secret
    const authError = requireCronSecret(req);
    if (authError) return authError;

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Wednesday Payouts] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Initialize Stripe client
    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
    if (!stripeSecretKey) {
      console.error("[Wednesday Payouts] Missing STRIPE_SECRET_KEY");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    const stripe = new Stripe(stripeSecretKey, {
      apiVersion: "2025-12-15.clover",
    });

    // Calculate date range (last Wednesday to this Wednesday, America/Chicago)
    const weekStart = getLastWednesday();
    const weekEnd = getThisWednesday();
    const dateRange = formatDateRange(weekStart, weekEnd);

    // Fetch churches with Stripe accounts
    const { data: churches, error: churchesError } = await supabase
      .from("churches")
      .select("church_id, display_name, legal_name, stripe_account_id, stripe_charges_enabled, stripe_payouts_enabled, stripe_onboarding_status, admin_emails, preferred_language")
      .not("stripe_account_id", "is", null);

    if (churchesError) {
      console.error("[Wednesday Payouts] Failed to fetch churches", {
        error: churchesError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Database error" },
        { status: 500 }
      );
    }

    if (!churches || churches.length === 0) {
      return NextResponse.json({
        ok: true,
        summary: {
          churchesProcessed: 0,
          emailsSent: 0,
          failures: 0,
        },
      });
    }

    // Process each church
    let churchesProcessed = 0;
    let emailsSent = 0;
    let failures = 0;
    const failuresList: Array<{ church_id: string; error: string }> = [];

    for (const church of churches as Church[]) {
      try {
        // Skip churches without admin emails
        if (!church.admin_emails || church.admin_emails.length === 0) {
          console.log(`[Wednesday Payouts] Skipping ${church.church_id} - no admin emails`);
          continue;
        }

        // Determine payout status
        let payoutStatus: string;
        if (!church.stripe_payouts_enabled || !church.stripe_charges_enabled) {
          payoutStatus = "Payouts not enabled—complete Stripe onboarding";
        } else {
          // For v1, rely on Stripe's automatic payout schedule
          // Connected accounts receive automatic payouts per their schedule
          payoutStatus = "Payout scheduled for Wednesday via Stripe Connect (automatic)";
        }

        // Calculate weekly total
        const { data: donations } = await supabase
          .from("donations")
          .select("amount_cents")
          .eq("church_id", church.church_id)
          .eq("status", "succeeded")
          .gte("created_at", weekStart.toISOString())
          .lt("created_at", weekEnd.toISOString());

        const weeklyTotal = donations?.reduce((sum, d) => sum + (d.amount_cents || 0), 0) || 0;
        const weeklyTotalFormatted = formatCurrency(weeklyTotal, "usd");

        // Generate and send email
        const email = generateDepositStatusEmail(
          church,
          dateRange.start,
          dateRange.end,
          weeklyTotal,
          weeklyTotalFormatted,
          payoutStatus,
          (church.preferred_language || "EN") as "EN" | "ES"
        );

        // Send email to each admin
        for (const adminEmail of church.admin_emails) {
          const result = await sendEmail(adminEmail, email.subject, email.html, email.text);
          if (result.success) {
            emailsSent++;
            console.log(`[Wednesday Payouts] Email sent to ${adminEmail} for church ${church.church_id}`);
          } else {
            failures++;
            failuresList.push({
              church_id: church.church_id,
              error: `Failed to send to ${adminEmail}: ${result.error}`,
            });
            console.error(`[Wednesday Payouts] Failed to send email to ${adminEmail}`, result.error);
          }
        }

        churchesProcessed++;
      } catch (err: any) {
        failures++;
        failuresList.push({
          church_id: church.church_id,
          error: err?.message || "Unknown error",
        });
        console.error(`[Wednesday Payouts] Error processing church ${church.church_id}`, err);
      }
    }

    const summary = {
      churchesProcessed,
      emailsSent,
      failures,
      failuresList: failuresList.length > 0 ? failuresList : undefined,
    };

    // Log job run
    await logJobRun("wednesday-payouts", "success", summary);

    return NextResponse.json({
      ok: true,
      summary,
    });
  } catch (err: any) {
    console.error("[Wednesday Payouts] Unexpected error", err);
    
    // Log job run error
    await logJobRun("wednesday-payouts", "error", undefined, err?.message || "Internal server error");

    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

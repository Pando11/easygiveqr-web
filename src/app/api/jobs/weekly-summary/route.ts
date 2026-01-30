import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireCronSecret } from "@/lib/requireAdmin";
import { logJobRun } from "@/lib/jobLogger";
import { generateEmail } from "@/lib/emailTemplates";
import { sendEmail } from "@/lib/email/sendEmail";
import {
  getLastWednesday,
  getThisWednesday,
  getPreviousWeekWednesday,
  getFirstDayOfMonth,
  formatDateRange,
} from "@/lib/dateUtils";

export const runtime = "nodejs";

interface Church {
  church_id: string;
  display_name: string;
  legal_name: string;
  admin_emails: string[];
  preferred_language: "EN" | "ES";
  status?: string;
}

interface DonationStats {
  weeklyTotal: number;
  oneTimeTotal: number;
  monthlyTotal: number;
  monthToDateTotal: number;
  previousWeekTotal: number;
}


/**
 * Calculate donation statistics for a church
 */
async function calculateDonationStats(
  supabase: ReturnType<typeof getSupabaseAdmin>,
  churchId: string,
  weekStart: Date,
  weekEnd: Date,
  monthStart: Date,
  previousWeekStart: Date,
  previousWeekEnd: Date
): Promise<DonationStats> {
  // Weekly total (this week)
  const { data: weeklyData } = await supabase
    .from("donations")
    .select("amount_cents")
    .eq("church_id", churchId)
    .gte("created_at", weekStart.toISOString())
    .lt("created_at", weekEnd.toISOString());

  // Month-to-date total
  const { data: monthData } = await supabase
    .from("donations")
    .select("amount_cents")
    .eq("church_id", churchId)
    .gte("created_at", monthStart.toISOString());

  // Previous week total
  const { data: prevWeekData } = await supabase
    .from("donations")
    .select("amount_cents")
    .eq("church_id", churchId)
    .gte("created_at", previousWeekStart.toISOString())
    .lt("created_at", previousWeekEnd.toISOString());

  const weeklyTotal = weeklyData?.reduce((sum, d) => sum + (d.amount_cents || 0), 0) || 0;
  const monthToDateTotal = monthData?.reduce((sum, d) => sum + (d.amount_cents || 0), 0) || 0;
  const previousWeekTotal = prevWeekData?.reduce((sum, d) => sum + (d.amount_cents || 0), 0) || 0;

  // TODO: Track one-time vs monthly donations
  // For now, assume all are one-time
  const oneTimeTotal = weeklyTotal;
  const monthlyTotal = 0;

  return {
    weeklyTotal,
    oneTimeTotal,
    monthlyTotal,
    monthToDateTotal,
    previousWeekTotal,
  };
}

/**
 * POST handler for weekly summary batch job
 * 
 * Secured with x-cron-secret header
 * 
 * Environment variables required:
 * - CRON_SECRET: Secret for authenticating cron requests
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
      console.error("[Weekly Summary] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Calculate date ranges (America/Chicago timezone)
    const weekStart = getLastWednesday();
    const weekEnd = getThisWednesday();
    const monthStart = getFirstDayOfMonth();
    const previousWeekStart = getPreviousWeekWednesday();
    const previousWeekEnd = weekStart;

    const dateRange = formatDateRange(weekStart, weekEnd);

    // Fetch active churches
    const { data: churches, error: churchesError } = await supabase
      .from("churches")
      .select("church_id, display_name, legal_name, admin_emails, preferred_language, status")
      .or("status.eq.active,status.is.null");

    if (churchesError) {
      console.error("[Weekly Summary] Failed to fetch churches", {
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
          console.log(`[Weekly Summary] Skipping ${church.church_id} - no admin emails`);
          continue;
        }

        // Calculate donation statistics
        const stats = await calculateDonationStats(
          supabase,
          church.church_id,
          weekStart,
          weekEnd,
          monthStart,
          previousWeekStart,
          previousWeekEnd
        );

        // Calculate week-over-week change percentage
        const weekOverWeekChange =
          stats.previousWeekTotal > 0
            ? ((stats.weeklyTotal - stats.previousWeekTotal) / stats.previousWeekTotal) * 100
            : stats.weeklyTotal > 0
            ? 100
            : 0;

        // Generate email
        const email = generateEmail(
          {
            churchDisplayName: church.display_name || church.legal_name || church.church_id,
            weekStart: dateRange.start,
            weekEnd: dateRange.end,
            weeklyTotal: stats.weeklyTotal,
            weeklyTotalFormatted: "", // Will be formatted in generateEmail
            oneTimeTotal: stats.oneTimeTotal,
            oneTimeTotalFormatted: "",
            monthlyTotal: stats.monthlyTotal,
            monthlyTotalFormatted: "",
            monthToDateTotal: stats.monthToDateTotal,
            monthToDateTotalFormatted: "",
            previousWeekTotal: stats.previousWeekTotal,
            previousWeekTotalFormatted: "",
            weekOverWeekChange,
            weekOverWeekChangeFormatted: "",
            currency: "usd",
          },
          church.preferred_language || "EN"
        );

        // Send email to each admin
        for (const adminEmail of church.admin_emails) {
          const result = await sendEmail({
            to: adminEmail,
            subject: email.subject,
            html: email.html,
            text: email.text,
          });
          if (result.success) {
            emailsSent++;
            console.log(`[Weekly Summary] Email sent to ${adminEmail} for church ${church.church_id}`);
          } else {
            failures++;
            failuresList.push({
              church_id: church.church_id,
              error: `Failed to send to ${adminEmail}: ${result.error}`,
            });
            console.error(`[Weekly Summary] Failed to send email to ${adminEmail}`, result.error);
          }
        }

        churchesProcessed++;
      } catch (err: any) {
        failures++;
        failuresList.push({
          church_id: church.church_id,
          error: err?.message || "Unknown error",
        });
        console.error(`[Weekly Summary] Error processing church ${church.church_id}`, err);
      }
    }

    const summary = {
      churchesProcessed,
      emailsSent,
      failures,
      failuresList: failuresList.length > 0 ? failuresList : undefined,
    };

    // Log job run
    await logJobRun("weekly-summary", "success", summary);

    return NextResponse.json({
      ok: true,
      summary,
    });
  } catch (err: any) {
    console.error("[Weekly Summary] Unexpected error", err);
    
    // Log job run error
    await logJobRun("weekly-summary", "error", undefined, err?.message || "Internal server error");

    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireCronSecret } from "@/lib/requireAdmin";
import { logJobRun } from "@/lib/jobLogger";
import { generateReceipt } from "@/lib/receiptTemplates";
import { sendEmail } from "@/lib/email/sendEmail";

export const runtime = "nodejs";

interface Church {
  church_id: string;
  display_name: string;
  legal_name: string;
  ein: string;
  preferred_language: "EN" | "ES";
}

interface DonorSummary {
  donor_email: string;
  total_amount_cents: number;
}


/**
 * Check if receipt has already been sent (idempotency)
 */
async function isReceiptSent(
  supabase: ReturnType<typeof getSupabaseAdmin>,
  year: number,
  churchId: string,
  donorEmail: string
): Promise<boolean> {
  const { data, error } = await supabase
    .from("annual_receipts_sent")
    .select("id")
    .eq("year", year)
    .eq("church_id", churchId)
    .eq("donor_email", donorEmail)
    .maybeSingle();

  if (error && error.code !== "PGRST116") {
    // PGRST116 is "no rows returned", which is fine
    console.error("[Annual Receipts] Error checking receipt status", {
      error: error.message,
    });
  }

  return !!data;
}

/**
 * Mark receipt as sent (idempotency)
 */
async function markReceiptSent(
  supabase: ReturnType<typeof getSupabaseAdmin>,
  year: number,
  churchId: string,
  donorEmail: string
): Promise<{ success: boolean; error?: string }> {
  const { error } = await supabase.from("annual_receipts_sent").insert({
    year,
    church_id: churchId,
    donor_email: donorEmail,
  });

  if (error) {
    // If it's a unique constraint violation, receipt was already sent (idempotent)
    if (error.code === "23505") {
      return { success: true };
    }
    return { success: false, error: error.message };
  }

  return { success: true };
}

/**
 * Get donor summaries for a church in a given year
 */
async function getDonorSummaries(
  supabase: ReturnType<typeof getSupabaseAdmin>,
  churchId: string,
  year: number
): Promise<DonorSummary[]> {
  const yearStart = new Date(year, 0, 1); // January 1, 00:00:00 UTC
  const yearEnd = new Date(year + 1, 0, 1); // January 1 of next year

  const { data, error } = await supabase
    .from("donations")
    .select("donor_email, amount_cents")
    .eq("church_id", churchId)
    .eq("status", "succeeded")
    .not("donor_email", "is", null)
    .gte("created_at", yearStart.toISOString())
    .lt("created_at", yearEnd.toISOString());

  if (error) {
    console.error("[Annual Receipts] Error fetching donations", {
      church_id: churchId,
      error: error.message,
    });
    return [];
  }

  if (!data) return [];

  // Group by donor_email and sum amounts
  const donorMap = new Map<string, number>();
  for (const donation of data) {
    if (donation.donor_email) {
      const current = donorMap.get(donation.donor_email) || 0;
      donorMap.set(donation.donor_email, current + (donation.amount_cents || 0));
    }
  }

  return Array.from(donorMap.entries()).map(([donor_email, total_amount_cents]) => ({
    donor_email,
    total_amount_cents,
  }));
}

/**
 * POST handler for annual receipts batch job
 * 
 * Secured with x-cron-secret header
 * 
 * Request body:
 * {
 *   "year": 2025,  // required
 *   "church_id": "EGQR-123"  // optional, for testing
 * }
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

    // Parse request body
    let body: { year?: number; church_id?: string };
    try {
      body = await req.json();
    } catch {
      return NextResponse.json(
        { ok: false, error: "Invalid JSON body" },
        { status: 400 }
      );
    }

    const year = body.year;
    const churchIdFilter = body.church_id;

    // Validate year
    if (!year || typeof year !== "number" || year < 2000 || year > 2100) {
      return NextResponse.json(
        { ok: false, error: "Invalid year. Must be between 2000 and 2100" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Annual Receipts] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch churches (all or filtered)
    let churchesQuery = supabase
      .from("churches")
      .select("church_id, display_name, legal_name, ein, preferred_language");

    if (churchIdFilter) {
      churchesQuery = churchesQuery.eq("church_id", churchIdFilter);
    }

    const { data: churches, error: churchesError } = await churchesQuery;

    if (churchesError) {
      console.error("[Annual Receipts] Failed to fetch churches", {
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
          receiptsSent: 0,
          receiptsSkipped: 0,
          failures: 0,
        },
      });
    }

    // Process each church
    let churchesProcessed = 0;
    let receiptsSent = 0;
    let receiptsSkipped = 0;
    let failures = 0;
    const failuresList: Array<{ church_id: string; donor_email: string; error: string }> = [];

    for (const church of churches as Church[]) {
      try {
        // Get donor summaries for this church and year
        const donorSummaries = await getDonorSummaries(supabase, church.church_id, year);

        if (donorSummaries.length === 0) {
          console.log(`[Annual Receipts] No donors found for church ${church.church_id} in year ${year}`);
          continue;
        }

        // Process each donor
        for (const donor of donorSummaries) {
          try {
            // Check if receipt already sent (idempotency)
            const alreadySent = await isReceiptSent(
              supabase,
              year,
              church.church_id,
              donor.donor_email
            );

            if (alreadySent) {
              console.log(
                `[Annual Receipts] Receipt already sent to ${donor.donor_email} for church ${church.church_id} year ${year}`
              );
              receiptsSkipped++;
              continue;
            }

            // Generate receipt email
            const email = generateReceipt(
              {
                churchDisplayName: church.display_name || church.legal_name || church.church_id,
                churchLegalName: church.legal_name || church.display_name || church.church_id,
                ein: church.ein || "N/A",
                year,
                totalAmount: donor.total_amount_cents,
                totalAmountFormatted: "", // Will be formatted in generateReceipt
                currency: "usd",
              },
              church.preferred_language || "EN"
            );

            // Send email
            const sendResult = await sendEmail({
              to: donor.donor_email,
              subject: email.subject,
              html: email.html,
              text: email.text,
            });

            if (sendResult.success) {
              // Mark as sent
              const markResult = await markReceiptSent(
                supabase,
                year,
                church.church_id,
                donor.donor_email
              );

              if (markResult.success) {
                receiptsSent++;
                console.log(
                  `[Annual Receipts] Receipt sent to ${donor.donor_email} for church ${church.church_id} year ${year}`
                );
              } else {
                failures++;
                failuresList.push({
                  church_id: church.church_id,
                  donor_email: donor.donor_email,
                  error: `Failed to mark as sent: ${markResult.error}`,
                });
                console.error(
                  `[Annual Receipts] Failed to mark receipt as sent for ${donor.donor_email}`,
                  markResult.error
                );
              }
            } else {
              failures++;
              failuresList.push({
                church_id: church.church_id,
                donor_email: donor.donor_email,
                error: sendResult.error || "Unknown error",
              });
              console.error(
                `[Annual Receipts] Failed to send receipt to ${donor.donor_email}`,
                sendResult.error
              );
            }
          } catch (err: any) {
            failures++;
            failuresList.push({
              church_id: church.church_id,
              donor_email: donor.donor_email,
              error: err?.message || "Unknown error",
            });
            console.error(
              `[Annual Receipts] Error processing donor ${donor.donor_email}`,
              err
            );
          }
        }

        churchesProcessed++;
      } catch (err: any) {
        failures++;
        console.error(`[Annual Receipts] Error processing church ${church.church_id}`, err);
      }
    }

    const summary = {
      year,
      churchesProcessed,
      receiptsSent,
      receiptsSkipped,
      failures,
      failuresList: failuresList.length > 0 ? failuresList : undefined,
    };

    // Log job run
    await logJobRun("annual-receipts", "success", summary);

    return NextResponse.json({
      ok: true,
      summary,
    });
  } catch (err: any) {
    console.error("[Annual Receipts] Unexpected error", err);
    
    // Log job run error
    await logJobRun("annual-receipts", "error", undefined, err?.message || "Internal server error");

    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

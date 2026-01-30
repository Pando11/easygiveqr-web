import { NextResponse } from "next/server";
import { requireAdminSecret } from "@/lib/requireAdmin";
import { sendEmail } from "@/lib/email/sendEmail";
import {
  weeklySummaryEN,
  generateEngagementEmailSubject,
  generateEngagementEmailHtml,
  generateEngagementEmailText,
} from "@/lib/email/templates";
import { generateReceipt } from "@/lib/receiptTemplates";
import type { EngagementEmailData } from "@/lib/email/templates";

export const runtime = "nodejs";

/**
 * POST handler to send a test email
 * 
 * Request body:
 * {
 *   "to_email": "test@example.com",
 *   "template": "weekly" | "annual" | "engagement",
 *   "language": "EN" | "ES"
 * }
 * 
 * Protected by x-admin-secret
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));

    const to_email = String(body?.to_email || "");
    const template = String(body?.template || "");
    const language = String(body?.language || "EN") as "EN" | "ES";

    // Validate to_email
    if (!to_email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to_email)) {
      return NextResponse.json(
        { ok: false, error: "Invalid or missing to_email" },
        { status: 400 }
      );
    }

    // Validate template
    if (!["weekly", "annual", "engagement"].includes(template)) {
      return NextResponse.json(
        { ok: false, error: "Invalid template. Must be 'weekly', 'annual', or 'engagement'" },
        { status: 400 }
      );
    }

    // Validate language
    if (!["EN", "ES"].includes(language)) {
      return NextResponse.json(
        { ok: false, error: "Invalid language. Must be 'EN' or 'ES'" },
        { status: 400 }
      );
    }

    let emailContent: { subject: string; html: string; text: string };

    // Generate email content based on template
    if (template === "weekly") {
      const email = weeklySummaryEN(
        {
          churchDisplayName: "Test Church",
          weekStart: "2026-01-20",
          weekEnd: "2026-01-27",
          weeklyTotal: 50000, // $500.00
          weeklyTotalFormatted: "",
          oneTimeTotal: 30000, // $300.00
          oneTimeTotalFormatted: "",
          monthlyTotal: 20000, // $200.00
          monthlyTotalFormatted: "",
          monthToDateTotal: 150000, // $1,500.00
          monthToDateTotalFormatted: "",
          previousWeekTotal: 45000, // $450.00
          previousWeekTotalFormatted: "",
          weekOverWeekChange: 11.1,
          weekOverWeekChangeFormatted: "",
          currency: "usd",
        },
        language
      );
      emailContent = email;
    } else if (template === "annual") {
      const email = generateReceipt(
        {
          churchDisplayName: "Test Church",
          churchLegalName: "Test Church Inc.",
          ein: "12-3456789",
          year: 2025,
          totalAmount: 500000, // $5,000.00
          totalAmountFormatted: "",
          currency: "usd",
        },
        language
      );
      emailContent = email;
    } else {
      // engagement
      const emailData: EngagementEmailData = {
        churchName: "Test Church",
        type: "prayer",
        name: "Test User",
        email: "test@example.com",
        message: "This is a test prayer request.",
      };
      emailContent = {
        subject: generateEngagementEmailSubject(emailData, language),
        html: generateEngagementEmailHtml(emailData, language),
        text: generateEngagementEmailText(emailData, language),
      };
    }

    // Send email
    const result = await sendEmail({
      to: to_email,
      subject: emailContent.subject,
      html: emailContent.html,
      text: emailContent.text,
    });

    if (!result.success) {
      return NextResponse.json(
        { ok: false, error: result.error || "Failed to send email" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      message: `Test email sent to ${to_email}`,
      template,
      language,
    });
  } catch (err: any) {
    console.error("[Email Test] Unexpected error", err);
    
    // Handle SENDGRID_FROM_EMAIL missing error
    if (err.message && err.message.includes("SENDGRID_FROM_EMAIL")) {
      return NextResponse.json(
        { ok: false, error: err.message },
        { status: 500 }
      );
    }

    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

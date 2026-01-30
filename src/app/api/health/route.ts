import { NextResponse } from "next/server";
import { APP_VERSION } from "@/lib/version";

export const runtime = "nodejs";

/**
 * GET handler for health check endpoint
 * 
 * Returns:
 * - 200: { ok: true, env: "production|preview|development" }
 * - 500: { ok: false, error: "Missing required environment variables" }
 * 
 * Checks that required environment variables exist (without printing values)
 */
export async function GET() {
  try {
    // Determine environment
    const vercelEnv = process.env.VERCEL_ENV || "development";
    let env: "production" | "preview" | "development" = "development";
    
    if (vercelEnv === "production") {
      env = "production";
    } else if (vercelEnv === "preview") {
      env = "preview";
    }

    // Check required environment variables exist (without printing values)
    const requiredVars = [
      "SUPABASE_URL",
      "SUPABASE_SERVICE_ROLE_KEY",
      "STRIPE_SECRET_KEY",
      "STRIPE_WEBHOOK_SECRET",
      "SENDGRID_API_KEY",
      "SENDGRID_FROM_EMAIL",
      "ADMIN_SECRET",
      "CRON_SECRET",
      // SITE_URL or NEXT_PUBLIC_SITE_URL (at least one required)
    ];

    const missing: string[] = [];

    // Check SITE_URL or NEXT_PUBLIC_SITE_URL (at least one must exist)
    const hasSiteUrl = process.env.SITE_URL || process.env.NEXT_PUBLIC_SITE_URL;
    if (!hasSiteUrl) {
      missing.push("SITE_URL or NEXT_PUBLIC_SITE_URL");
    }
    for (const varName of requiredVars) {
      const value = process.env[varName];
      if (!value || value.trim().length === 0) {
        missing.push(varName);
      }
    }

    if (missing.length > 0) {
      return NextResponse.json(
        {
          ok: false,
          env,
          error: "Missing required environment variables",
          missing_vars: missing,
        },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      env,
      version: APP_VERSION,
      timestamp: new Date().toISOString(),
    });
  } catch (err: any) {
    return NextResponse.json(
      {
        ok: false,
        error: "Health check failed",
      },
      { status: 500 }
    );
  }
}

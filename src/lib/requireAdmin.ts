import { NextResponse } from "next/server";
import { getEnv } from "@/lib/env";

/**
 * Require admin secret header (x-admin-secret)
 * Returns 401 if missing or invalid
 */
export function requireAdminSecret(req: Request): NextResponse | null {
  const adminSecret = req.headers.get("x-admin-secret");
  const expectedSecret = getEnv("ADMIN_SECRET");

  if (!adminSecret || adminSecret !== expectedSecret) {
    return NextResponse.json(
      { ok: false, error: "Unauthorized: Missing or invalid x-admin-secret header" },
      { status: 401 }
    );
  }

  return null; // Authorized
}

/**
 * Require cron secret header (x-cron-secret) or query parameter (?cron=...)
 * Returns 401 if missing or invalid
 * 
 * Supports both:
 * - Header: x-cron-secret (for manual testing)
 * - Query parameter: ?cron=... (for Vercel Cron which can't send custom headers)
 */
export function requireCronSecret(req: Request): NextResponse | null {
  const expectedSecret = getEnv("CRON_SECRET");

  // Try header first (for manual testing)
  const cronSecretHeader = req.headers.get("x-cron-secret");
  
  // Try query parameter (for Vercel Cron)
  const url = new URL(req.url);
  const cronSecretQuery = url.searchParams.get("cron");

  const cronSecret = cronSecretHeader || cronSecretQuery;

  if (!cronSecret || cronSecret !== expectedSecret) {
    return NextResponse.json(
      { ok: false, error: "Unauthorized: Missing or invalid cron secret (use x-cron-secret header or ?cron= query parameter)" },
      { status: 401 }
    );
  }

  return null; // Authorized
}

/**
 * Helper to check auth and return early if unauthorized
 * Usage: const authError = requireAdminSecret(req); if (authError) return authError;
 */
export function checkAdminAuth(req: Request): NextResponse | null {
  return requireAdminSecret(req);
}

export function checkCronAuth(req: Request): NextResponse | null {
  return requireCronSecret(req);
}

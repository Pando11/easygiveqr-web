import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * GET handler to list engagement submissions
 * 
 * Query parameters:
 * - church_id (required)
 * - type (optional): prayer, visitor, or volunteer
 * - status (optional): open or completed
 * 
 * Returns last 100 submissions, newest first
 * Protected by x-admin-secret
 */
export async function GET(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const { searchParams } = new URL(req.url);
    const church_id = searchParams.get("church_id");
    const type = searchParams.get("type");
    const status = searchParams.get("status");

    // Validate church_id
    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required parameter: church_id" },
        { status: 400 }
      );
    }

    // Validate type if provided
    if (type && !["prayer", "visitor", "volunteer"].includes(type)) {
      return NextResponse.json(
        { ok: false, error: "Invalid type. Must be 'prayer', 'visitor', or 'volunteer'" },
        { status: 400 }
      );
    }

    // Validate status if provided
    if (status && !["open", "completed"].includes(status)) {
      return NextResponse.json(
        { ok: false, error: "Invalid status. Must be 'open' or 'completed'" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Admin Engagement] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Build query
    let query = supabase
      .from("engagement_submissions")
      .select("*")
      .eq("church_id", church_id)
      .order("created_at", { ascending: false })
      .limit(100);

    if (type) {
      query = query.eq("type", type);
    }

    if (status) {
      query = query.eq("status", status);
    }

    const { data: submissions, error: queryError } = await query;

    if (queryError) {
      console.error("[Admin Engagement] Failed to query submissions", {
        error: queryError.message,
      });
      return NextResponse.json(
        { ok: false, error: `Database error: ${queryError.message}` },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      submissions: submissions || [],
      count: submissions?.length || 0,
    });
  } catch (err: any) {
    console.error("[Admin Engagement] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

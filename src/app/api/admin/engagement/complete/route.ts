import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * PATCH handler to mark an engagement submission as completed
 * 
 * Request body:
 * {
 *   "id": "uuid-of-submission"
 * }
 * 
 * Protected by x-admin-secret
 */
export async function PATCH(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));

    const id = body?.id;

    // Validate id
    if (!id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: id" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Admin Engagement Complete] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Check if submission exists
    const { data: existing, error: checkError } = await supabase
      .from("engagement_submissions")
      .select("id, status")
      .eq("id", id)
      .single();

    if (checkError || !existing) {
      return NextResponse.json(
        { ok: false, error: "Submission not found" },
        { status: 404 }
      );
    }

    // Update status to completed
    const { data: updated, error: updateError } = await supabase
      .from("engagement_submissions")
      .update({
        status: "completed",
        completed_at: new Date().toISOString(),
      })
      .eq("id", id)
      .select("id, status, completed_at")
      .single();

    if (updateError) {
      console.error("[Admin Engagement Complete] Failed to update submission", {
        id,
        error: updateError.message,
      });
      return NextResponse.json(
        { ok: false, error: `Database error: ${updateError.message}` },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      submission: updated,
    });
  } catch (err: any) {
    console.error("[Admin Engagement Complete] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

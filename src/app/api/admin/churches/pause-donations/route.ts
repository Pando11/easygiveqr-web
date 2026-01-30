import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * PATCH handler to pause/unpause donations for a church
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123",
 *   "donations_paused": true
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
    const church_id = String(body?.church_id || "");
    const donations_paused = body?.donations_paused;

    // Validate church_id
    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    // Validate donations_paused is a boolean
    if (typeof donations_paused !== "boolean") {
      return NextResponse.json(
        { ok: false, error: "Missing or invalid field: donations_paused (must be boolean)" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Pause Donations] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Check if church exists
    const { data: existingChurch, error: checkError } = await supabase
      .from("churches")
      .select("church_id")
      .eq("church_id", church_id)
      .single();

    if (checkError || !existingChurch) {
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // Update donations_paused
    const { data: updatedChurch, error: updateError } = await supabase
      .from("churches")
      .update({ donations_paused })
      .eq("church_id", church_id)
      .select("church_id, donations_paused")
      .single();

    if (updateError) {
      console.error("[Pause Donations] Failed to update church", {
        church_id,
        error: updateError.message,
      });
      return NextResponse.json(
        { ok: false, error: `Database error: ${updateError.message}` },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      church_id: updatedChurch.church_id,
      donations_paused: updatedChurch.donations_paused,
    });
  } catch (err: any) {
    console.error("[Pause Donations] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

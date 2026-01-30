import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * PATCH handler to update monthly_enabled flag for a church
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123",
 *   "monthly_enabled": true
 * }
 * 
 * Protected by x-admin-secret header
 */
export async function PATCH(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));

    const church_id = String(body?.church_id || "");
    const monthly_enabled = body?.monthly_enabled;

    // Validate church_id
    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    // Validate monthly_enabled is a boolean
    if (typeof monthly_enabled !== "boolean") {
      return NextResponse.json(
        { ok: false, error: "Missing or invalid field: monthly_enabled (must be boolean)" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Admin Monthly] Failed to initialize Supabase client");
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

    // Update monthly_enabled
    const { data: updatedChurch, error: updateError } = await supabase
      .from("churches")
      .update({ monthly_enabled })
      .eq("church_id", church_id)
      .select("church_id, monthly_enabled")
      .single();

    if (updateError) {
      console.error("[Admin Monthly] Failed to update church", {
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
      monthly_enabled: updatedChurch.monthly_enabled,
    });
  } catch (err: any) {
    console.error("[Admin Monthly] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

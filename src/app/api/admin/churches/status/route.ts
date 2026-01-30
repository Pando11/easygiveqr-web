import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { requireAdminSecret } from "@/lib/requireAdmin";

export const runtime = "nodejs";

/**
 * PATCH handler to update church status
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123",
 *   "status": "pending" | "active" | "paused" | "closed"
 * }
 * 
 * Protected by x-admin-secret
 * Sets activated_at when status becomes active
 */
export async function PATCH(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    const body = await req.json().catch(() => ({} as any));
    const church_id = String(body?.church_id || "");
    const status = String(body?.status || "");

    // Validate church_id
    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    // Validate status
    const validStatuses = ["pending", "active", "paused", "closed"];
    if (!status || !validStatuses.includes(status)) {
      return NextResponse.json(
        { ok: false, error: `Invalid status. Must be one of: ${validStatuses.join(", ")}` },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Church Status] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Check if church exists
    const { data: existingChurch, error: checkError } = await supabase
      .from("churches")
      .select("church_id, status")
      .eq("church_id", church_id)
      .single();

    if (checkError || !existingChurch) {
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // Prepare update data
    const updateData: any = { status };

    // Set activated_at when status becomes active (if not already set)
    if (status === "active" && !existingChurch.status || existingChurch.status !== "active") {
      const { data: currentChurch } = await supabase
        .from("churches")
        .select("activated_at")
        .eq("church_id", church_id)
        .single();

      if (!currentChurch?.activated_at) {
        updateData.activated_at = new Date().toISOString();
      }
    }

    // Update church status
    const { data: updatedChurch, error: updateError } = await supabase
      .from("churches")
      .update(updateData)
      .eq("church_id", church_id)
      .select("church_id, status, activated_at")
      .single();

    if (updateError) {
      console.error("[Church Status] Failed to update church", {
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
      status: updatedChurch.status,
      activated_at: updatedChurch.activated_at,
    });
  } catch (err: any) {
    console.error("[Church Status] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

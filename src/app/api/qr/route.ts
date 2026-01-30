import { NextResponse } from "next/server";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { getDonationUrl } from "@/lib/siteUrl";

export const runtime = "nodejs";

/**
 * GET handler to retrieve QR code information for a church
 * 
 * Query parameters:
 * - church_id: Church ID (required)
 * 
 * Returns:
 * - 200: { ok: true, church_id, donate_url, qr_code_url }
 * - 404: { ok: false, error: "Church not found" }
 * - 400: { ok: false, error: "Missing church_id" }
 */
export async function GET(req: Request) {
  try {
    // Get church_id from query parameters
    const { searchParams } = new URL(req.url);
    const church_id = searchParams.get("church_id");

    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required parameter: church_id" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[QR Get] Failed to initialize Supabase client");
      return NextResponse.json(
        { ok: false, error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Fetch church
    const { data: church, error: churchError } = await supabase
      .from("churches")
      .select("church_id, qr_code_url")
      .eq("church_id", church_id)
      .single();

    if (churchError) {
      console.error("[QR Get] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    const donateUrl = getDonationUrl(church_id);

    return NextResponse.json({
      ok: true,
      church_id: church.church_id,
      donate_url: donateUrl,
      qr_code_url: church.qr_code_url || null,
    });
  } catch (err: any) {
    console.error("[QR Get] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

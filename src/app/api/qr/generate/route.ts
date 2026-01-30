import { NextResponse } from "next/server";
import QRCode from "qrcode";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import { uploadToSupabaseStorage, checkStorageBucket } from "@/lib/supabaseStorage";
import { requireAdminSecret } from "@/lib/requireAdmin";
import { getDonationUrl } from "@/lib/siteUrl";

export const runtime = "nodejs";

const STORAGE_BUCKET = "church-assets";
const QR_CODE_PATH_PREFIX = "qr";

/**
 * POST handler to generate and store QR code for a church
 * 
 * Request body:
 * {
 *   "church_id": "EGQR-123",
 *   "force": false  // optional, regenerate even if exists
 * }
 * 
 * Environment variables required:
 * - NEXT_PUBLIC_SITE_URL or SITE_URL: Base URL for donation links
 * - SUPABASE_URL: Supabase project URL
 * - SUPABASE_SERVICE_ROLE_KEY: Supabase service role key
 */
export async function POST(req: Request) {
  try {
    // Verify admin secret
    const authError = requireAdminSecret(req);
    if (authError) return authError;

    // Parse request body
    let body: { church_id?: string; force?: boolean };
    try {
      body = await req.json();
    } catch {
      return NextResponse.json(
        { ok: false, error: "Invalid JSON body" },
        { status: 400 }
      );
    }

    const church_id = body.church_id;
    const force = body.force || false;

    if (!church_id) {
      return NextResponse.json(
        { ok: false, error: "Missing required field: church_id" },
        { status: 400 }
      );
    }

    // Get Supabase admin client
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[QR Generate] Failed to initialize Supabase client");
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
      console.error("[QR Generate] Failed to fetch church", {
        error: churchError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Church not found" },
        { status: 404 }
      );
    }

    // Check if QR code already exists and force is not set
    if (church.qr_code_url && !force) {
      return NextResponse.json({
        ok: true,
        qr_code_url: church.qr_code_url,
        message: "QR code already exists. Use force=true to regenerate.",
      });
    }

    // Check if storage bucket exists
    const bucketExists = await checkStorageBucket(STORAGE_BUCKET);
    if (!bucketExists) {
      console.error(`[QR Generate] Storage bucket '${STORAGE_BUCKET}' does not exist`);
      return NextResponse.json(
        {
          ok: false,
          error: `Storage bucket '${STORAGE_BUCKET}' not found. Please create it in Supabase Dashboard.`,
        },
        { status: 500 }
      );
    }

    // Generate donation URL (throws error if SITE_URL missing in production)
    let donationUrl: string;
    try {
      donationUrl = getDonationUrl(church_id);
    } catch (err: any) {
      console.error("[QR Generate] Site URL configuration error", err);
      return NextResponse.json(
        { ok: false, error: `Site URL not configured: ${err.message}` },
        { status: 500 }
      );
    }

    // Generate QR code as PNG buffer
    let qrCodeBuffer: Buffer;
    try {
      qrCodeBuffer = await QRCode.toBuffer(donationUrl, {
        type: "png",
        width: 512,
        margin: 2,
        errorCorrectionLevel: "M",
      });
    } catch (err: any) {
      console.error("[QR Generate] Failed to generate QR code", err);
      return NextResponse.json(
        { ok: false, error: "Failed to generate QR code" },
        { status: 500 }
      );
    }

    // Upload to Supabase Storage
    const filePath = `${QR_CODE_PATH_PREFIX}/${church_id}.png`;
    const uploadResult = await uploadToSupabaseStorage(
      STORAGE_BUCKET,
      filePath,
      qrCodeBuffer,
      "image/png"
    );

    if (uploadResult.error) {
      console.error("[QR Generate] Failed to upload QR code", uploadResult.error);
      return NextResponse.json(
        { ok: false, error: `Failed to upload QR code: ${uploadResult.error}` },
        { status: 500 }
      );
    }

    // Update church record with QR code URL
    const { error: updateError } = await supabase
      .from("churches")
      .update({
        qr_code_url: uploadResult.url,
        qr_code_updated_at: new Date().toISOString(),
      })
      .eq("church_id", church_id);

    if (updateError) {
      console.error("[QR Generate] Failed to update church", {
        error: updateError.message,
      });
      return NextResponse.json(
        { ok: false, error: "Database error" },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      qr_code_url: uploadResult.url,
      donate_url: donationUrl,
    });
  } catch (err: any) {
    console.error("[QR Generate] Unexpected error", err);
    return NextResponse.json(
      { ok: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}

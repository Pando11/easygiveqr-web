import QRCode from "qrcode";
import Stripe from "stripe";
import { getSupabaseAdmin } from "./supabaseAdmin";
import { uploadToSupabaseStorage, checkStorageBucket } from "./supabaseStorage";
import { getDonationUrl } from "./siteUrl";

const STORAGE_BUCKET = "church-assets";
const QR_CODE_PATH_PREFIX = "qr";
const LOGO_PATH_PREFIX = "logos";

/**
 * Generate and upload QR code for a church
 */
export async function generateQRCode(churchId: string): Promise<{ url: string; error?: string }> {
  try {
    // Check if storage bucket exists
    const bucketExists = await checkStorageBucket(STORAGE_BUCKET);
    if (!bucketExists) {
      return { url: "", error: `Storage bucket '${STORAGE_BUCKET}' not found` };
    }

    // Generate donation URL
    const donationUrl = getDonationUrl(churchId);

    // Generate QR code as PNG buffer
    const qrCodeBuffer = await QRCode.toBuffer(donationUrl, {
      type: "png",
      width: 512,
      margin: 2,
      errorCorrectionLevel: "M",
    });

    // Upload to Supabase Storage
    const filePath = `${QR_CODE_PATH_PREFIX}/${churchId}.png`;
    const uploadResult = await uploadToSupabaseStorage(
      STORAGE_BUCKET,
      filePath,
      qrCodeBuffer,
      "image/png"
    );

    if (uploadResult.error) {
      return { url: "", error: uploadResult.error };
    }

    return { url: uploadResult.url };
  } catch (err: any) {
    console.error("[Onboarding] Failed to generate QR code", err);
    return { url: "", error: err?.message || "Failed to generate QR code" };
  }
}

/**
 * Create Stripe Connect account for a church
 */
export async function createStripeConnectAccount(
  churchId: string,
  legalName: string
): Promise<{ accountId: string; error?: string }> {
  try {
    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
    if (!stripeSecretKey) {
      return { accountId: "", error: "STRIPE_SECRET_KEY not configured" };
    }

    const stripe = new Stripe(stripeSecretKey, {
      apiVersion: "2025-12-15.clover",
    });

    // Create new Stripe Connect Express account
    const account = await stripe.accounts.create({
      type: "express",
      country: "US", // Default to US
      capabilities: {
        card_payments: { requested: true },
        transfers: { requested: true },
      },
      metadata: {
        church_id: churchId,
        legal_name: legalName,
      },
    });

    return { accountId: account.id };
  } catch (err: any) {
    console.error("[Onboarding] Failed to create Stripe account", err);
    return { accountId: "", error: err?.message || "Failed to create Stripe account" };
  }
}

/**
 * Generate Stripe Connect onboarding link
 */
export async function generateStripeOnboardingLink(
  accountId: string,
  returnUrl: string,
  refreshUrl: string
): Promise<{ url: string; error?: string }> {
  try {
    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
    if (!stripeSecretKey) {
      return { url: "", error: "STRIPE_SECRET_KEY not configured" };
    }

    const stripe = new Stripe(stripeSecretKey, {
      apiVersion: "2025-12-15.clover",
    });

    // Create account link for onboarding
    const accountLink = await stripe.accountLinks.create({
      account: accountId,
      refresh_url: refreshUrl,
      return_url: returnUrl,
      type: "account_onboarding",
    });

    return { url: accountLink.url };
  } catch (err: any) {
    console.error("[Onboarding] Failed to generate onboarding link", err);
    return { url: "", error: err?.message || "Failed to generate onboarding link" };
  }
}

/**
 * Upload logo to Supabase Storage
 */
export async function uploadLogo(
  churchId: string,
  fileBuffer: Buffer,
  fileExtension: string,
  contentType: string
): Promise<{ url: string; error?: string }> {
  try {
    // Check if storage bucket exists
    const bucketExists = await checkStorageBucket(STORAGE_BUCKET);
    if (!bucketExists) {
      return { url: "", error: `Storage bucket '${STORAGE_BUCKET}' not found` };
    }

    // Upload to Supabase Storage
    const filePath = `${LOGO_PATH_PREFIX}/${churchId}.${fileExtension}`;
    const uploadResult = await uploadToSupabaseStorage(
      STORAGE_BUCKET,
      filePath,
      fileBuffer,
      contentType
    );

    if (uploadResult.error) {
      return { url: "", error: uploadResult.error };
    }

    return { url: uploadResult.url };
  } catch (err: any) {
    console.error("[Onboarding] Failed to upload logo", err);
    return { url: "", error: err?.message || "Failed to upload logo" };
  }
}

/**
 * Site URL helper
 * Ensures production URLs never use localhost
 */

/**
 * Get the site URL for building absolute URLs
 * 
 * In production: MUST use SITE_URL or NEXT_PUBLIC_SITE_URL
 * In development: allows falling back to request origin
 * 
 * @param requestOrigin - Optional request origin (for development fallback)
 * @returns Site URL (e.g., https://easygiveqr.net)
 * @throws Error if in production and SITE_URL/NEXT_PUBLIC_SITE_URL is missing
 */
export function getSiteUrl(requestOrigin?: string | null): string {
  const isProduction = process.env.NODE_ENV === "production";
  const siteUrl = process.env.SITE_URL || process.env.NEXT_PUBLIC_SITE_URL;

  // In production, SITE_URL is required
  if (isProduction) {
    if (!siteUrl) {
      throw new Error(
        "SITE_URL or NEXT_PUBLIC_SITE_URL must be set in production. " +
        "Set it to https://easygiveqr.net in Vercel environment variables."
      );
    }
    return siteUrl;
  }

  // In development, prefer env var, fallback to request origin or localhost
  if (siteUrl) {
    return siteUrl;
  }

  if (requestOrigin) {
    return requestOrigin;
  }

  // Final fallback for development
  return "http://localhost:3000";
}

/**
 * Get the donation URL for a church
 * 
 * @param churchId - Church ID (e.g., "EGQR-123")
 * @param requestOrigin - Optional request origin (for development fallback)
 * @returns Full donation URL
 */
export function getDonationUrl(churchId: string, requestOrigin?: string | null): string {
  const siteUrl = getSiteUrl(requestOrigin);
  return `${siteUrl}/donate?church_id=${encodeURIComponent(churchId)}`;
}

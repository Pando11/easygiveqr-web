import { redirect } from "next/navigation";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";

export const runtime = "nodejs";

/**
 * GET handler for email verification page
 * 
 * Query parameters:
 * - church_id: Church ID
 * - email: Email address to verify
 * - token: Verification token
 * 
 * Marks the email as verified if token matches
 */
export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: { church_id?: string; email?: string; token?: string };
}) {
  const church_id = searchParams.church_id || "";
  const email = searchParams.email || "";
  const token = searchParams.token || "";

  // Validate parameters
  if (!church_id || !email || !token) {
    return (
      <main style={{ padding: 40, fontFamily: "sans-serif", textAlign: "center" }}>
        <h1 style={{ color: "#DC2626" }}>Invalid Verification Link</h1>
        <p style={{ color: "#666", marginTop: 16 }}>
          Missing required parameters. Please check your email for the complete verification link.
        </p>
      </main>
    );
  }

  try {
    const supabase = getSupabaseAdmin();

    // Find verification record
    const { data: verification, error: findError } = await supabase
      .from("email_verifications")
      .select("*")
      .eq("church_id", church_id)
      .eq("email", email)
      .eq("token", token)
      .eq("status", "pending")
      .single();

    if (findError || !verification) {
      return (
        <main style={{ padding: 40, fontFamily: "sans-serif", textAlign: "center" }}>
          <h1 style={{ color: "#DC2626" }}>Verification Failed</h1>
          <p style={{ color: "#666", marginTop: 16 }}>
            Invalid or expired verification link. Please request a new verification email.
          </p>
        </main>
      );
    }

    // Check if token is expired (7 days)
    const createdAt = new Date(verification.created_at);
    const now = new Date();
    const daysSinceCreation = (now.getTime() - createdAt.getTime()) / (1000 * 60 * 60 * 24);

    if (daysSinceCreation > 7) {
      return (
        <main style={{ padding: 40, fontFamily: "sans-serif", textAlign: "center" }}>
          <h1 style={{ color: "#DC2626" }}>Verification Expired</h1>
          <p style={{ color: "#666", marginTop: 16 }}>
            This verification link has expired. Please request a new verification email.
          </p>
        </main>
      );
    }

    // Mark as verified
    const { error: updateError } = await supabase
      .from("email_verifications")
      .update({
        status: "verified",
        verified_at: new Date().toISOString(),
      })
      .eq("id", verification.id);

    if (updateError) {
      return (
        <main style={{ padding: 40, fontFamily: "sans-serif", textAlign: "center" }}>
          <h1 style={{ color: "#DC2626" }}>Verification Error</h1>
          <p style={{ color: "#666", marginTop: 16 }}>
            An error occurred while verifying your email. Please try again.
          </p>
        </main>
      );
    }

    // Success - show confirmation
    return (
      <main style={{ padding: 40, fontFamily: "sans-serif", textAlign: "center", maxWidth: 600, margin: "0 auto" }}>
        <h1 style={{ color: "#10B981", marginBottom: 16 }}>Email Verified</h1>
        <p style={{ color: "#666", fontSize: 16, lineHeight: 1.6, marginBottom: 32 }}>
          Your email address <strong>{email}</strong> has been successfully verified.
        </p>
        <p style={{ color: "#999", fontSize: 14 }}>
          You can now receive important notifications from EasyGiveQR.
        </p>
      </main>
    );
  } catch (err: any) {
    return (
      <main style={{ padding: 40, fontFamily: "sans-serif", textAlign: "center" }}>
        <h1 style={{ color: "#DC2626" }}>Verification Error</h1>
        <p style={{ color: "#666", marginTop: 16 }}>
          An unexpected error occurred. Please try again later.
        </p>
      </main>
    );
  }
}

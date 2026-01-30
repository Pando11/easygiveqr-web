import { NextResponse } from "next/server";
import Stripe from "stripe";
import { createClient } from "@supabase/supabase-js";

export const runtime = "nodejs";

function jsonError(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

export async function POST(req: Request) {
  try {
    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
    const supabaseUrl = process.env.SUPABASE_URL;
    const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

    if (!stripeSecretKey) return jsonError("Missing STRIPE_SECRET_KEY", 500);
    if (!supabaseUrl) return jsonError("Missing SUPABASE_URL", 500);
    if (!serviceRoleKey) return jsonError("Missing SUPABASE_SERVICE_ROLE_KEY", 500);

    const stripe = new Stripe(stripeSecretKey, { apiVersion: "2025-12-15.clover" });
    const supabase = createClient(supabaseUrl, serviceRoleKey, {
      auth: { persistSession: false },
    });

    const body = await req.json().catch(() => ({} as any));
    const church_id = String(body?.church_id || "");
    const session_id = String(body?.session_id || "");

    if (!church_id) return jsonError("Missing church_id", 400);
    if (!session_id) return jsonError("Missing session_id", 400);

    // Pull the session from Stripe so we can store real amount/currency/status safely.
    const session = await stripe.checkout.sessions.retrieve(session_id);

    // Basic validation: require paid session (or at least completed)
    const paymentStatus = session.payment_status || "unknown";
    const amountTotal = session.amount_total ?? null; // cents
    const currency = session.currency ?? "usd";

    // Optional (recommended): verify Stripe metadata church_id matches
    const metaChurchId = (session.metadata?.church_id as string | undefined) || "";
    if (metaChurchId && metaChurchId !== church_id) {
      return jsonError("church_id does not match Stripe session metadata", 400);
    }

    if (amountTotal === null) {
      return jsonError("Stripe session missing amount_total", 400);
    }

    const status =
      paymentStatus === "paid" ? "succeeded" :
      paymentStatus === "unpaid" ? "unpaid" :
      paymentStatus;

    // Idempotent insert: if this session already exists, do not duplicate.
    const { error } = await supabase
      .from("donations")
      .upsert(
        {
          church_id,
          stripe_session_id: session.id,
          amount_cents: amountTotal,
          currency,
          status,
        },
        { onConflict: "stripe_session_id" }
      );

    if (error) return jsonError(error.message, 500);

    return NextResponse.json({
      ok: true,
      inserted: true,
      church_id,
      stripe_session_id: session.id,
      amount_cents: amountTotal,
      currency,
      status,
    });
  } catch (e: any) {
    return jsonError(e?.message || "Server error", 500);
  }
}

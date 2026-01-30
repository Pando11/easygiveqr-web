import { NextResponse } from "next/server";

export async function GET() {
  const pk = process.env.STRIPE_PUBLISHABLE_KEY || "";
  const sk = process.env.STRIPE_SECRET_KEY || "";

  return NextResponse.json({
    ok: true,
    publishable_prefix: pk.slice(0, 7),
    secret_prefix: sk.slice(0, 7),
    mode: pk.startsWith("pk_live_") ? "live" : pk.startsWith("pk_test_") ? "test" : "unknown",
  });
}

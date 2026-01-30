import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";

function jsonError(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const churchId = searchParams.get("church_id");

  if (!churchId) return jsonError("Missing required parameter: church_id", 400);

  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl) return jsonError("Server misconfigured: SUPABASE_URL missing", 500);
  if (!serviceRoleKey)
    return jsonError("Server misconfigured: SUPABASE_SERVICE_ROLE_KEY missing", 500);

  const supabase = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false },
  });

  const { data, error } = await supabase
      .from("churches")
      .select(
        "church_id, display_name, legal_name, ein, logo_url, primary_color, donation_phrase, preferred_language, status, subscription_status, stripe_charges_enabled, stripe_payouts_enabled, monthly_enabled, donations_paused"
      )
      .eq("church_id", churchId)
      .maybeSingle();

  if (error) return jsonError(`Supabase error: ${error.message}`, 500);
  if (!data) return jsonError("Church not found", 404);

  return NextResponse.json({ ok: true, church: data });
}

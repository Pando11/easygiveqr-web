/**
 * Production Smoke Test
 * 
 * Run: node ops/smoke/smoke-prod.ts EGQR-TEST
 * Requires Node 18+ (native fetch)
 */

const churchId = process.argv[2];
if (!churchId) {
  console.error("Usage: node ops/smoke/smoke-prod.ts EGQR-TEST");
  process.exit(1);
}

const BASE = "https://easygiveqr.net";

async function check(url: string, expect: number[] = [200], options: RequestInit = {}) {
  try {
    const res = await fetch(url, { ...options, redirect: "follow" });
    const ok = expect.includes(res.status);
    const text = await res.text().catch(() => "");
    const status = ok ? "✅" : "❌";
    console.log(`${status} ${res.status} ${url}`);
    if (!ok) {
      console.log(`   Response: ${text.slice(0, 500)}`);
      return false;
    }
    return true;
  } catch (err: any) {
    console.error(`❌ Error checking ${url}:`, err.message);
    return false;
  }
}

async function main() {
  console.log("=".repeat(80));
  console.log("Production Smoke Test");
  console.log("=".repeat(80));
  console.log(`Base URL: ${BASE}`);
  console.log(`Church ID: ${churchId}`);
  console.log("");

  let allPassed = true;

  // 1. Health endpoint (critical for ops visibility)
  console.log("1. Health Endpoint");
  const healthPassed = await check(`${BASE}/api/health`, [200]);
  if (!healthPassed) {
    console.log("   ⚠️  WARNING: Health endpoint missing or failing. Add /api/health for ops visibility.");
    allPassed = false;
  }
  console.log("");

  // 2. Donate page should render
  console.log("2. Donation Page");
  const donatePassed = await check(`${BASE}/donate?church_id=${encodeURIComponent(churchId)}`, [200]);
  if (!donatePassed) allPassed = false;
  console.log("");

  // 3. Stripe webhook should NOT allow GET; 400 or 405 is fine
  console.log("3. Webhook Endpoint (should reject GET)");
  const webhookPassed = await check(`${BASE}/api/stripe-webhook`, [400, 405]);
  if (!webhookPassed) allPassed = false;
  console.log("");

  // 4. Church API endpoint
  console.log("4. Church API Endpoint");
  const churchApiPassed = await check(`${BASE}/api/church?church_id=${encodeURIComponent(churchId)}`, [200]);
  if (!churchApiPassed) allPassed = false;
  console.log("");

  // Summary
  console.log("=".repeat(80));
  if (allPassed) {
    console.log("✅ All smoke checks passed");
    process.exit(0);
  } else {
    console.log("❌ Some smoke checks failed");
    process.exit(1);
  }
}

main().catch((e) => {
  console.error("❌ Smoke test failed with error:", e);
  process.exit(1);
});

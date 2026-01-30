/**
 * Simple Schema Snapshot Script
 * 
 * Prints table structure by querying information_schema directly
 * Works with Supabase REST API
 * 
 * Usage:
 *   node scripts/schema-snapshot-simple.js
 * 
 * Environment variables:
 *   SUPABASE_URL - Supabase project URL
 *   SUPABASE_SERVICE_ROLE_KEY - Supabase service role key
 */

const { createClient } = require("@supabase/supabase-js");

async function main() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set");
    console.error("Usage: SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... node scripts/schema-snapshot-simple.js");
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  console.log("=".repeat(80));
  console.log("Schema Snapshot - Churches & Donations");
  console.log("=".repeat(80));
  console.log(`Generated: ${new Date().toISOString()}`);
  console.log("");

  // Get churches table structure by sampling
  console.log("Table: churches");
  console.log("-".repeat(80));
  try {
    const { data: churchSample, error } = await supabase
      .from("churches")
      .select("*")
      .limit(1)
      .maybeSingle();

    if (!error && churchSample) {
      console.log("Columns (inferred from sample):");
      Object.keys(churchSample).forEach((key) => {
        const value = churchSample[key];
        let typeHint = "unknown";
        if (value === null) typeHint = "nullable";
        else if (typeof value === "string") typeHint = "text";
        else if (typeof value === "number") typeHint = "number";
        else if (typeof value === "boolean") typeHint = "boolean";
        else if (Array.isArray(value)) typeHint = "array";
        else if (typeof value === "object") typeHint = "jsonb";

        const preview = value === null 
          ? "null" 
          : typeof value === "string" 
            ? value.substring(0, 40) 
            : typeof value === "object" 
              ? JSON.stringify(value).substring(0, 40)
              : String(value);

        console.log(`  - ${key.padEnd(30)} ${typeHint.padEnd(10)} (${preview}...)`);
      });
    } else {
      console.log("  (No data to sample - table may be empty)");
    }
  } catch (err) {
    console.error(`  Error: ${err.message}`);
  }

  console.log("");

  // Get donations table structure
  console.log("Table: donations");
  console.log("-".repeat(80));
  try {
    const { data: donationSample, error } = await supabase
      .from("donations")
      .select("*")
      .limit(1)
      .maybeSingle();

    if (!error && donationSample) {
      console.log("Columns (inferred from sample):");
      Object.keys(donationSample).forEach((key) => {
        const value = donationSample[key];
        let typeHint = "unknown";
        if (value === null) typeHint = "nullable";
        else if (typeof value === "string") typeHint = "text";
        else if (typeof value === "number") typeHint = "number";
        else if (typeof value === "boolean") typeHint = "boolean";
        else if (Array.isArray(value)) typeHint = "array";
        else if (typeof value === "object") typeHint = "jsonb";

        const preview = value === null 
          ? "null" 
          : typeof value === "string" 
            ? value.substring(0, 40) 
            : typeof value === "object" 
              ? JSON.stringify(value).substring(0, 40)
              : String(value);

        console.log(`  - ${key.padEnd(30)} ${typeHint.padEnd(10)} (${preview}...)`);
      });
    } else {
      console.log("  (No data to sample - table may be empty)");
    }
  } catch (err) {
    console.error(`  Error: ${err.message}`);
  }

  console.log("");
  console.log("=".repeat(80));
  console.log("Note: For complete schema, check Supabase Dashboard → Database → Tables");
  console.log("Or run migrations in order to see the full schema definition");
  console.log("=".repeat(80));
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});

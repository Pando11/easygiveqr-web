/**
 * Schema Snapshot Script
 * 
 * Prints current table columns for churches and donations tables
 * Useful for sanity checks and documentation
 * 
 * Usage:
 *   node scripts/schema-snapshot.js
 * 
 * Environment variables:
 *   SUPABASE_URL - Supabase project URL
 *   SUPABASE_SERVICE_ROLE_KEY - Supabase service role key
 */

const { createClient } = require("@supabase/supabase-js");

async function getTableColumns(supabase, tableName) {
  const { data, error } = await supabase.rpc("exec_sql", {
    sql: `
      SELECT 
        column_name,
        data_type,
        is_nullable,
        column_default,
        character_maximum_length
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = $1
      ORDER BY ordinal_position;
    `,
    params: [tableName],
  });

  if (error) {
    // Fallback: direct query
    const { data: directData, error: directError } = await supabase
      .from("information_schema.columns")
      .select("column_name, data_type, is_nullable, column_default, character_maximum_length")
      .eq("table_schema", "public")
      .eq("table_name", tableName)
      .order("ordinal_position");

    if (directError) {
      console.error(`Error fetching columns for ${tableName}:`, directError);
      return null;
    }
    return directData;
  }

  return data;
}

async function getTableIndexes(supabase, tableName) {
  const { data, error } = await supabase.rpc("exec_sql", {
    sql: `
      SELECT 
        indexname,
        indexdef
      FROM pg_indexes
      WHERE schemaname = 'public'
        AND tablename = $1;
    `,
    params: [tableName],
  });

  if (error) {
    console.warn(`Could not fetch indexes for ${tableName} (this is optional)`);
    return [];
  }

  return data || [];
}

async function main() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !supabaseKey) {
    console.error("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set");
    process.exit(1);
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  console.log("=".repeat(80));
  console.log("Schema Snapshot");
  console.log("=".repeat(80));
  console.log(`Generated: ${new Date().toISOString()}`);
  console.log(`Supabase URL: ${supabaseUrl}`);
  console.log("");

  const tables = ["churches", "donations", "engagement_submissions", "job_runs", "stripe_webhook_events"];

  for (const tableName of tables) {
    console.log("-".repeat(80));
    console.log(`Table: ${tableName}`);
    console.log("-".repeat(80));

    // Get columns using a direct SQL query via Supabase
    // Note: This requires a custom RPC function or we can query via REST
    // For simplicity, we'll use a workaround with raw SQL if available
    try {
      // Try to get columns via a query (this may not work without a custom RPC)
      // Fallback: manual query structure
      const { data: columns, error: colError } = await supabase
        .from("_realtime")
        .select("*")
        .limit(0);

      if (colError && colError.code !== "PGRST116") {
        // If we can't query, try alternative approach
        console.log(`  Note: Cannot auto-fetch columns for ${tableName}`);
        console.log(`  Please check Supabase Dashboard → Table Editor → ${tableName}`);
        console.log("");
        continue;
      }

      // Alternative: Use pg_catalog query if we have a custom RPC
      // For now, print a manual check instruction
      console.log(`  Columns: (check Supabase Dashboard for current schema)`);
      console.log(`  Indexes: (check Supabase Dashboard for current indexes)`);
      console.log("");

      // Try to get a sample row to infer structure
      const { data: sample, error: sampleError } = await supabase
        .from(tableName)
        .select("*")
        .limit(1)
        .maybeSingle();

      if (!sampleError && sample) {
        console.log(`  Sample columns (from first row):`);
        Object.keys(sample).forEach((key) => {
          const value = sample[key];
          const type = value === null ? "null" : typeof value;
          const preview = value === null ? "null" : String(value).substring(0, 30);
          console.log(`    - ${key}: ${type} (${preview}...)`);
        });
      }
    } catch (err) {
      console.error(`  Error checking ${tableName}:`, err.message);
    }

    console.log("");
  }

  console.log("=".repeat(80));
  console.log("Note: For detailed schema, use Supabase Dashboard → Database → Tables");
  console.log("=".repeat(80));
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});

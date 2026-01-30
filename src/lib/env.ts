/**
 * Environment variable validation
 * 
 * Validates required environment variables on import and throws helpful errors
 * if any are missing. This ensures we fail fast at startup rather than
 * discovering missing vars at runtime.
 */

interface EnvConfig {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_ROLE_KEY: string;
  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
  SENDGRID_API_KEY: string;
  SENDGRID_FROM_EMAIL: string;
  ADMIN_SECRET: string;
  CRON_SECRET: string;
  NEXT_PUBLIC_SITE_URL: string;
  NODE_ENV: string;
  // Optional but should be set
  DONATIONS_PAUSED?: string; // Global kill switch (defaults to false if not set)
}

const requiredEnvVars: (keyof EnvConfig)[] = [
  "SUPABASE_URL",
  "SUPABASE_SERVICE_ROLE_KEY",
  "STRIPE_SECRET_KEY",
  "STRIPE_WEBHOOK_SECRET",
  "SENDGRID_API_KEY",
  "SENDGRID_FROM_EMAIL",
  "ADMIN_SECRET",
  "CRON_SECRET",
  "NEXT_PUBLIC_SITE_URL",
  "NODE_ENV",
];

/**
 * Validate all required environment variables
 * Throws error with helpful message if any are missing
 */
export function validateEnv(): void {
  const missing: string[] = [];

  for (const varName of requiredEnvVars) {
    const value = process.env[varName];
    if (!value || value.trim().length === 0) {
      missing.push(varName);
    }
  }

  if (missing.length > 0) {
    throw new Error(
      `Missing required environment variables: ${missing.join(", ")}\n` +
        `Please add them to .env.local or your deployment environment.`
    );
  }
}

/**
 * Get environment variable with validation
 * Returns the value or throws if missing
 */
export function getEnv(key: keyof EnvConfig): string {
  const value = process.env[key];
  if (!value || value.trim().length === 0) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

// Validate on module load (server-side only)
// In production, fail fast - don't allow server to start with missing env vars
if (typeof window === "undefined") {
  try {
    validateEnv();
  } catch (err) {
    // In production, throw to prevent server from starting
    if (process.env.NODE_ENV === "production") {
      console.error("[Env Validation] CRITICAL: Missing required environment variables in production!");
      console.error(err);
      // Force process exit in production
      process.exit(1);
    } else {
      // In development, log but allow startup (for better DX)
      console.error("[Env Validation] Environment variable validation failed:", err);
      console.warn("[Env Validation] Server will start but may fail at runtime. Fix missing env vars.");
    }
  }
}

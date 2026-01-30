/**
 * Simple in-memory rate limiting for serverless environments
 * 
 * Best-effort rate limiting per IP address.
 * Note: In serverless (Vercel), this is per-instance and will reset on cold starts.
 * For production-grade rate limiting, use a Redis-backed solution.
 */

import { NextResponse } from "next/server";

interface RateLimitEntry {
  count: number;
  resetAt: number;
}

// In-memory store (per-instance)
const rateLimitStore = new Map<string, RateLimitEntry>();

// Cleanup old entries every 5 minutes
if (typeof global !== "undefined") {
  const cleanupInterval = setInterval(() => {
    const now = Date.now();
    for (const [key, entry] of rateLimitStore.entries()) {
      if (entry.resetAt < now) {
        rateLimitStore.delete(key);
      }
    }
  }, 5 * 60 * 1000); // 5 minutes

  // Store interval ID to allow cleanup if needed
  (global as any).__rateLimitCleanup = cleanupInterval;
}

/**
 * Get client IP from request
 * Handles Vercel's proxy headers
 */
function getClientIP(req: Request): string {
  // Check Vercel's forwarded headers first
  const forwardedFor = req.headers.get("x-forwarded-for");
  if (forwardedFor) {
    // x-forwarded-for can contain multiple IPs, take the first one
    return forwardedFor.split(",")[0].trim();
  }

  const realIP = req.headers.get("x-real-ip");
  if (realIP) {
    return realIP;
  }

  // Fallback (won't work in serverless, but good for local dev)
  return "unknown";
}

/**
 * Get rate limit key with user agent heuristic
 * Combines IP + user agent hash for better abuse detection
 */
function getRateLimitKey(req: Request, maxRequests: number, windowMs: number): string {
  const ip = getClientIP(req);
  const userAgent = req.headers.get("user-agent") || "unknown";
  
  // Simple hash of user agent (first 20 chars) for heuristic
  // This helps detect bots/automated requests
  const uaHash = userAgent.substring(0, 20).replace(/[^a-zA-Z0-9]/g, "");
  
  return `${ip}:${uaHash}:${maxRequests}:${windowMs}`;
}

/**
 * Check rate limit for a request
 * 
 * @param req - Request object
 * @param maxRequests - Maximum requests allowed in the window
 * @param windowMs - Time window in milliseconds
 * @returns null if allowed, NextResponse with 429 if rate limited
 */
export function checkRateLimit(
  req: Request,
  maxRequests: number = 100,
  windowMs: number = 60 * 1000 // 1 minute default
): NextResponse | null {
  const now = Date.now();
  const key = getRateLimitKey(req, maxRequests, windowMs);

  const entry = rateLimitStore.get(key);

  if (!entry || entry.resetAt < now) {
    // Create new entry or reset expired entry
    rateLimitStore.set(key, {
      count: 1,
      resetAt: now + windowMs,
    });
    return null; // Allowed
  }

  if (entry.count >= maxRequests) {
    // Rate limited
    const retryAfter = Math.ceil((entry.resetAt - now) / 1000);
    return NextResponse.json(
      {
        ok: false,
        error: "rate_limited",
        message: "Rate limit exceeded. Please try again later.",
        retry_after: retryAfter,
      },
      {
        status: 429,
        headers: {
          "Retry-After": String(retryAfter),
          "X-RateLimit-Limit": String(maxRequests),
          "X-RateLimit-Remaining": "0",
          "X-RateLimit-Reset": String(entry.resetAt),
        },
      }
    );
  }

  // Increment count
  entry.count++;
  return null; // Allowed
}

/**
 * Rate limit configuration for different endpoints
 */
export const RATE_LIMITS = {
  checkout: { maxRequests: 15, windowMs: 60 * 1000 }, // 15 requests per minute (hardened)
  donation: { maxRequests: 20, windowMs: 60 * 1000 }, // 20 requests per minute (hardened)
  engagement: { maxRequests: 10, windowMs: 60 * 1000 }, // 10 requests per minute (hardened)
} as const;

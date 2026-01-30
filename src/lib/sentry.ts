/**
 * Sentry initialization and error tracking
 * Server-side only - no PII sent
 * 
 * Note: For Next.js, Sentry should be initialized in next.config.js
 * This file provides helper functions for capturing errors
 */

let sentryInitialized = false;

// Lazy import to avoid breaking if Sentry is not installed
let Sentry: any = null;

async function getSentry() {
  if (!Sentry && process.env.SENTRY_DSN) {
    try {
      Sentry = await import("@sentry/nextjs");
      sentryInitialized = true;
    } catch (err) {
      console.warn("[Sentry] Package not installed - run: npm install @sentry/nextjs");
      return null;
    }
  }
  return Sentry;
}

const SENTRY_DSN = process.env.SENTRY_DSN;

/**
 * Initialize Sentry (call once at app startup)
 * 
 * Note: For Next.js, Sentry should be initialized via next.config.js
 * This function is a fallback for manual initialization
 */
export async function initSentry() {
  if (!SENTRY_DSN) {
    console.log("[Sentry] Not configured (SENTRY_DSN not set)");
    return;
  }

  try {
    const SentryModule = await getSentry();
    if (!SentryModule) return;

    SentryModule.init({
      dsn: SENTRY_DSN,
      environment: process.env.NODE_ENV || "development",
      tracesSampleRate: 0.1,
      beforeSend(event: any, hint: any) {
        return sanitizeEvent(event);
      },
    });

    console.log("[Sentry] Initialized");
  } catch (err: any) {
    console.error("[Sentry] Failed to initialize", err?.message);
  }
}

function sanitizeEvent(event: any): any {
  // Remove PII from events
  if (event.request) {
    if (event.request.url) {
      event.request.url = event.request.url.replace(
        /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
        "[email-redacted]"
      );
    }
    if (event.request.headers) {
      Object.keys(event.request.headers).forEach((key) => {
        const value = event.request.headers[key];
        if (typeof value === "string" && value.includes("@")) {
          event.request.headers[key] = "[email-redacted]";
        }
      });
    }
  }
  if (event.extra) {
    Object.keys(event.extra).forEach((key) => {
      const value = event.extra![key];
      if (typeof value === "string") {
        event.extra![key] = value.replace(
          /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
          "[email-redacted]"
        );
      }
    });
  }
  return event;
}

/**
 * Capture an exception
 * 
 * @param error - Error object or message
 * @param context - Additional context (no PII)
 */
export async function captureException(error: Error | string, context?: Record<string, any>) {
  if (!SENTRY_DSN) {
    return;
  }

  try {
    const SentryModule = await getSentry();
    if (!SentryModule) return;

    const safeContext = sanitizeContext(context);
    SentryModule.captureException(error, {
      extra: safeContext,
    });
  } catch (err) {
    console.error("[Sentry] Failed to capture exception", err);
  }
}

/**
 * Capture a message (non-error)
 * 
 * @param message - Message to log
 * @param level - Log level (info, warning, error)
 * @param context - Additional context (no PII)
 */
export async function captureMessage(
  message: string,
  level: "info" | "warning" | "error" = "info",
  context?: Record<string, any>
) {
  if (!SENTRY_DSN) {
    return;
  }

  try {
    const SentryModule = await getSentry();
    if (!SentryModule) return;

    const safeContext = sanitizeContext(context);
    SentryModule.captureMessage(message, {
      level,
      extra: safeContext,
    });
  } catch (err) {
    console.error("[Sentry] Failed to capture message", err);
  }
}

function sanitizeContext(context?: Record<string, any>): Record<string, any> {
  const safeContext: Record<string, any> = {};
  if (context) {
    Object.keys(context).forEach((key) => {
      const value = context[key];
      if (typeof value === "string") {
        if (value.includes("@")) {
          safeContext[key] = "[email-redacted]";
        } else {
          safeContext[key] = value;
        }
      } else {
        safeContext[key] = value;
      }
    });
  }
  return safeContext;
}

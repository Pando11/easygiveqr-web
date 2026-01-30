/**
 * Structured request logging
 * Generates request IDs and logs requests/errors without PII
 */

import { randomUUID } from "crypto";

/**
 * Generate a request ID for tracking
 */
export function generateRequestId(): string {
  return randomUUID();
}

/**
 * Log a request (without PII)
 */
export function logRequest(
  requestId: string,
  route: string,
  method: string,
  metadata?: Record<string, any>
): void {
  const logData: Record<string, any> = {
    request_id: requestId,
    route,
    method,
    timestamp: new Date().toISOString(),
  };

  if (metadata) {
    // Filter out PII from metadata
    const safeMetadata: Record<string, any> = {};
    for (const [key, value] of Object.entries(metadata)) {
      // Don't log full emails, names, or addresses
      if (
        key.includes("email") ||
        key.includes("name") ||
        key.includes("address") ||
        key.includes("phone")
      ) {
        // Only log first few characters if it's a string
        if (typeof value === "string" && value.length > 0) {
          safeMetadata[key] = value.substring(0, 3) + "***";
        } else {
          safeMetadata[key] = "***";
        }
      } else {
        safeMetadata[key] = value;
      }
    }
    Object.assign(logData, safeMetadata);
  }

  console.log(`[Request] ${JSON.stringify(logData)}`);
}

/**
 * Log an error (without PII)
 */
export function logError(
  requestId: string,
  route: string,
  errorCode: string,
  errorMessage: string,
  metadata?: Record<string, any>
): void {
  const logData: Record<string, any> = {
    request_id: requestId,
    route,
    error_code: errorCode,
    error_message: errorMessage,
    timestamp: new Date().toISOString(),
  };

  if (metadata) {
    // Filter out PII from metadata
    const safeMetadata: Record<string, any> = {};
    for (const [key, value] of Object.entries(metadata)) {
      if (
        key.includes("email") ||
        key.includes("name") ||
        key.includes("address") ||
        key.includes("phone")
      ) {
        if (typeof value === "string" && value.length > 0) {
          safeMetadata[key] = value.substring(0, 3) + "***";
        } else {
          safeMetadata[key] = "***";
        }
      } else {
        safeMetadata[key] = value;
      }
    }
    Object.assign(logData, safeMetadata);
  }

  console.error(`[Error] ${JSON.stringify(logData)}`);
}

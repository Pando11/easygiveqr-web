/**
 * Standardized API response helpers
 * Ensures consistent error format across all API routes
 */

import { NextResponse } from "next/server";

export interface ApiError {
  ok: false;
  error: string; // Error code (e.g., "church_not_found", "invalid_amount")
  message?: string; // Human-readable message (optional, for user-facing errors)
}

export interface ApiSuccess<T = any> {
  ok: true;
  data?: T;
  [key: string]: any; // Allow additional fields
}

/**
 * Create a standardized error response
 * 
 * @param errorCode - Machine-readable error code
 * @param status - HTTP status code (default 400)
 * @param message - Optional human-readable message
 * @returns NextResponse with standardized error format
 */
export function apiError(
  errorCode: string,
  status: number = 400,
  message?: string
): NextResponse<ApiError> {
  const response: ApiError = {
    ok: false,
    error: errorCode,
  };

  if (message) {
    response.message = message;
  }

  return NextResponse.json(response, { status });
}

/**
 * Create a standardized success response
 * 
 * @param data - Optional data to include
 * @param status - HTTP status code (default 200)
 * @param additionalFields - Optional additional fields
 * @returns NextResponse with standardized success format
 */
export function apiSuccess<T = any>(
  data?: T,
  status: number = 200,
  additionalFields?: Record<string, any>
): NextResponse<ApiSuccess<T>> {
  const response: ApiSuccess<T> = {
    ok: true,
  };

  if (data !== undefined) {
    response.data = data;
  }

  if (additionalFields) {
    Object.assign(response, additionalFields);
  }

  return NextResponse.json(response, { status });
}

/**
 * Common error codes
 */
export const ERROR_CODES = {
  // Validation errors (400)
  MISSING_FIELD: "missing_field",
  INVALID_INPUT: "invalid_input",
  INVALID_AMOUNT: "invalid_amount",
  INVALID_FREQUENCY: "invalid_frequency",
  
  // Not found (404)
  CHURCH_NOT_FOUND: "church_not_found",
  DONATION_NOT_FOUND: "donation_not_found",
  SUBMISSION_NOT_FOUND: "submission_not_found",
  
  // Forbidden (403)
  CHURCH_NOT_ACTIVE: "church_not_active",
  MONTHLY_NOT_ENABLED: "monthly_not_enabled",
  
  // Unauthorized (401)
  UNAUTHORIZED: "unauthorized",
  
  // Server errors (500)
  SERVER_ERROR: "server_error",
  DATABASE_ERROR: "database_error",
  CONFIGURATION_ERROR: "configuration_error",
} as const;

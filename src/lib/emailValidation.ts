/**
 * Email validation and normalization utilities
 */

/**
 * Validate and normalize email addresses
 * 
 * @param emails - Comma-separated string or array of emails
 * @returns Array of normalized, validated email addresses
 * @throws Error if validation fails
 */
export function validateAndNormalizeEmails(emails: string | string[]): string[] {
  // Convert to array if string
  const emailArray = typeof emails === "string" 
    ? emails.split(",").map(e => e.trim()).filter(e => e.length > 0)
    : emails.map(e => String(e).trim()).filter(e => e.length > 0);

  if (emailArray.length === 0) {
    throw new Error("At least one email address is required");
  }

  // Basic email regex (RFC 5322 simplified)
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  const normalized: string[] = [];
  const seen = new Set<string>();

  for (const email of emailArray) {
    const normalizedEmail = email.toLowerCase().trim();
    
    // Validate format
    if (!emailRegex.test(normalizedEmail)) {
      throw new Error(`Invalid email format: ${email}`);
    }

    // Check for duplicates
    if (seen.has(normalizedEmail)) {
      continue; // Skip duplicates
    }

    seen.add(normalizedEmail);
    normalized.push(normalizedEmail);
  }

  if (normalized.length === 0) {
    throw new Error("At least one valid email address is required");
  }

  return normalized;
}

/**
 * Validate a single email address
 * 
 * @param email - Email address to validate
 * @returns true if valid, false otherwise
 */
export function isValidEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email.toLowerCase().trim());
}

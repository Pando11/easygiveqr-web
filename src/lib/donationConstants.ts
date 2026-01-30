/**
 * Donation constants
 */

// Allowed preset amounts in cents
export const DONATION_PRESETS = [500, 1000, 2500, 5000] as const; // $5, $10, $25, $50

// Frequency types
export type DonationFrequency = "one_time" | "monthly";

// Validate if amount is a valid preset
export function isValidPresetAmount(amount: number): boolean {
  return DONATION_PRESETS.includes(amount as any);
}

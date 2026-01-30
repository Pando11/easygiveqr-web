/**
 * Church eligibility for donations
 * 
 * Determines if a church is eligible to accept donations based on:
 * - Church status (must be 'active')
 * - Subscription status (must be 'active' or 'trialing')
 * - Stripe Connect onboarding (charges_enabled and payouts_enabled must be true)
 */

export interface ChurchRow {
  status?: string | null;
  subscription_status?: string | null;
  stripe_charges_enabled?: boolean | null;
  stripe_payouts_enabled?: boolean | null;
  donations_paused?: boolean | null;
}

/**
 * Check if a church is eligible to accept donations
 * 
 * @param church - Church row from database
 * @param allowInactiveOverride - Admin override flag (only for local dev, not production)
 * @returns true if eligible, false otherwise
 */
export function isChurchEligibleForDonations(
  church: ChurchRow,
  allowInactiveOverride: boolean = false
): boolean {
  // Admin override (only in non-production environments)
  if (allowInactiveOverride && process.env.NODE_ENV !== "production") {
    return true;
  }

  // Check global kill switch
  const globalKillSwitch = process.env.DONATIONS_PAUSED === "true";
  if (globalKillSwitch) {
    return false;
  }

  // Check per-church pause flag
  if (church.donations_paused === true) {
    return false;
  }

  // Check church status (paused and closed are blocked)
  if (church.status !== "active") {
    return false;
  }

  // Check subscription status
  const validSubscriptionStatuses = ["active", "trialing"];
  if (!church.subscription_status || !validSubscriptionStatuses.includes(church.subscription_status)) {
    return false;
  }

  // Check Stripe Connect onboarding
  if (!church.stripe_charges_enabled || !church.stripe_payouts_enabled) {
    return false;
  }

  return true;
}

/**
 * Get reason why church is not eligible (for error messages)
 */
export function getEligibilityReason(church: ChurchRow): string {
  // Check global kill switch
  if (process.env.DONATIONS_PAUSED === "true") {
    return "donations_paused_global";
  }

  // Check per-church pause
  if (church.donations_paused === true) {
    return "donations_paused_church";
  }

  // Check church status
  if (church.status !== "active") {
    if (church.status === "paused" || church.status === "closed") {
      return "church_paused_or_closed";
    }
    return "church_status";
  }

  // Check subscription status
  const validSubscriptionStatuses = ["active", "trialing"];
  if (!church.subscription_status || !validSubscriptionStatuses.includes(church.subscription_status)) {
    return "subscription_status";
  }

  // Check Stripe Connect onboarding
  if (!church.stripe_charges_enabled || !church.stripe_payouts_enabled) {
    return "stripe_connect";
  }

  return "unknown";
}

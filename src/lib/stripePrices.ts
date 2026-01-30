import Stripe from "stripe";

/**
 * Get or create a Stripe price for a donation amount
 * For monthly donations, creates a recurring price
 * For one-time donations, uses price_data in checkout session
 */
export async function getOrCreateDonationPrice(
  stripe: Stripe,
  amountCents: number,
  frequency: "one_time" | "monthly"
): Promise<string | null> {
  // For one-time donations, we use price_data in checkout session
  // No need to create a price
  if (frequency === "one_time") {
    return null;
  }

  // For monthly donations, we need a recurring price
  // Try to find existing price first
  const prices = await stripe.prices.list({
    active: true,
    type: "recurring",
    limit: 100,
  });

  // Look for matching monthly donation price
  const existingPrice = prices.data.find(
    (price) =>
      price.unit_amount === amountCents &&
      price.currency === "usd" &&
      price.recurring?.interval === "month" &&
      price.metadata?.donation === "true"
  );

  if (existingPrice) {
    return existingPrice.id;
  }

  // Create product and price if not found
  const product = await stripe.products.create({
    name: `Monthly Donation - $${(amountCents / 100).toFixed(2)}`,
    description: `Monthly recurring donation of $${(amountCents / 100).toFixed(2)}`,
    metadata: {
      donation: "true",
    },
  });

  const price = await stripe.prices.create({
    product: product.id,
    unit_amount: amountCents,
    currency: "usd",
    recurring: {
      interval: "month",
    },
    metadata: {
      donation: "true",
    },
  });

  return price.id;
}

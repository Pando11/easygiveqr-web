import { NextResponse } from "next/server";
import Stripe from "stripe";
import { getSupabaseAdmin } from "@/lib/supabaseAdmin";

export const runtime = "nodejs";

/**
 * GET handler for quick browser check
 */
export async function GET() {
  return NextResponse.json({ ok: true });
}

/**
 * POST handler for Stripe webhook events
 * 
 * Environment variables required:
 * - STRIPE_SECRET_KEY: Stripe secret key for API operations
 * - STRIPE_WEBHOOK_SECRET: Webhook signing secret (whsec_...)
 * - SUPABASE_URL: Supabase project URL
 * - SUPABASE_SERVICE_ROLE_KEY: Supabase service role key (bypasses RLS)
 */
export async function POST(req: Request) {
  try {
    // Validate required environment variables
    const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
    const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

    if (!stripeSecretKey) {
      console.error("[Stripe Webhook] Missing STRIPE_SECRET_KEY");
      return NextResponse.json(
        { error: "Server configuration error" },
        { status: 500 }
      );
    }

    if (!webhookSecret) {
      console.error("[Stripe Webhook] Missing STRIPE_WEBHOOK_SECRET");
      return NextResponse.json(
        { error: "Server configuration error" },
        { status: 500 }
      );
    }

    // Initialize Stripe client
    const stripe = new Stripe(stripeSecretKey, {
      apiVersion: "2025-12-15.clover",
    });

    // Read raw body for signature verification (must use .text() not .json())
    const rawBody = await req.text();
    const signature = req.headers.get("stripe-signature");

    if (!signature) {
      console.error("[Stripe Webhook] Missing stripe-signature header");
      return NextResponse.json(
        { error: "Missing signature" },
        { status: 400 }
      );
    }

    // Verify webhook signature
    let event: Stripe.Event;
    try {
      event = stripe.webhooks.constructEvent(rawBody, signature, webhookSecret);
    } catch (err: any) {
      console.error("[Stripe Webhook] Signature verification failed");
      
      // Log failed webhook event
      try {
        const supabase = getSupabaseAdmin();
        await supabase.from("stripe_webhook_events").insert({
          event_id: null,
          event_type: "signature_verification_failed",
          status: "error",
          error_message: "Invalid signature",
        });
      } catch (logErr) {
        // Ignore logging errors
      }
      
      return NextResponse.json(
        { error: "Invalid signature" },
        { status: 400 }
      );
    }

    // Get Supabase admin client for logging
    let supabase;
    try {
      supabase = getSupabaseAdmin();
    } catch (err: any) {
      console.error("[Stripe Webhook] Failed to initialize Supabase client for logging");
      // Continue without logging - don't break webhook processing
    }

    // Log webhook event (before processing) - use upsert for idempotency
    // If event_id already exists, this is a duplicate event and we should ignore it
    if (supabase) {
      try {
        // Check if event already exists (for idempotency)
        const { data: existingEvent } = await supabase
          .from("stripe_webhook_events")
          .select("event_id, status")
          .eq("event_id", event.id)
          .maybeSingle();

        if (existingEvent) {
          // Event already processed - return early (idempotent)
          console.log(`[Stripe Webhook] Duplicate event detected: ${event.id} - already processed`);
          return NextResponse.json({ received: true, duplicate: true }, { status: 200 });
        }

        // Insert new event
        const { error: insertError } = await supabase
          .from("stripe_webhook_events")
          .insert({
            event_id: event.id,
            event_type: event.type,
            status: "success", // Will be updated if processing fails
            processed_at: new Date().toISOString(),
          });

        if (insertError) {
          // If it's a duplicate key error (race condition), event was just inserted by another request
          if (insertError.code === "23505") {
            console.log(`[Stripe Webhook] Duplicate event (race condition): ${event.id} - ignoring`);
            return NextResponse.json({ received: true, duplicate: true }, { status: 200 });
          }
          throw insertError;
        }
      } catch (logErr: any) {
        // If it's a duplicate, return early (already processed)
        if (logErr?.code === "23505") {
          console.log(`[Stripe Webhook] Duplicate event: ${event.id} - ignoring`);
          return NextResponse.json({ received: true, duplicate: true }, { status: 200 });
        }
        // Other errors - log but don't break webhook processing
        console.error("[Stripe Webhook] Failed to log event", logErr);
      }
    }

    // Handle checkout.session.completed event
    if (event.type === "checkout.session.completed") {
      const session = event.data.object as Stripe.Checkout.Session;

      // Extract church_id from metadata (required)
      const church_id = session.metadata?.church_id;

      // Handle subscription checkout (mode === "subscription")
      if (session.mode === "subscription") {
        if (!church_id) {
          console.error("[Stripe Webhook] Missing church_id in subscription session metadata", {
            session_id: session.id,
          });
          
          if (supabase) {
            try {
              await supabase
                .from("stripe_webhook_events")
                .update({
                  status: "error",
                  error_message: "Missing required field: church_id",
                })
                .eq("event_id", event.id);
            } catch (logErr) {
              // Ignore logging errors
            }
          }
          
          return NextResponse.json(
            { error: "Missing required field: church_id" },
            { status: 400 }
          );
        }

        // Get Supabase admin client (if not already initialized)
        if (!supabase) {
          try {
            supabase = getSupabaseAdmin();
          } catch (err: any) {
            console.error("[Stripe Webhook] Failed to initialize Supabase client");
            return NextResponse.json(
              { error: "Server configuration error" },
              { status: 500 }
            );
          }
        }

        // Get subscription ID from session
        const subscriptionId = session.subscription as string;
        const customerId = session.customer as string;

        if (!subscriptionId || !customerId) {
          console.error("[Stripe Webhook] Missing subscription or customer in session", {
            session_id: session.id,
          });
          return NextResponse.json(
            { received: true, error: "Missing subscription or customer" },
            { status: 200 }
          );
        }

        // Update church with subscription information
        const { error: updateError } = await supabase
          .from("churches")
          .update({
            stripe_subscription_id: subscriptionId,
            stripe_customer_id: customerId,
            subscription_status: "active",
            subscription_started_at: new Date().toISOString(),
            subscription_canceled_at: null,
          })
          .eq("church_id", church_id);

        if (updateError) {
          console.error("[Stripe Webhook] Failed to update church subscription", {
            church_id,
            error: updateError.message,
          });
          
          try {
            await supabase
              .from("stripe_webhook_events")
              .update({
                status: "error",
                error_message: `Database error: ${updateError.message}`,
              })
              .eq("event_id", event.id);
          } catch (logErr) {
            // Ignore logging errors
          }
        }

        return NextResponse.json({ received: true }, { status: 200 });
      }

      // Handle donation checkout (mode === "payment")
      // Extract required fields from session
      const stripe_session_id = session.id;
      const amount_cents = session.amount_total ?? 0;
      const currency = session.currency ?? "usd";
      const payment_status = session.payment_status ?? "succeeded";

      // Extract donor information from customer_details
      const donor_email = session.customer_details?.email || null;
      const donor_name = session.customer_details?.name || null;
      const donor_address = session.customer_details?.address
        ? {
            line1: session.customer_details.address.line1 || null,
            line2: session.customer_details.address.line2 || null,
            city: session.customer_details.address.city || null,
            state: session.customer_details.address.state || null,
            postal_code: session.customer_details.address.postal_code || null,
            country: session.customer_details.address.country || null,
          }
        : null;

      // Validate church_id is present
      if (!church_id) {
        console.error("[Stripe Webhook] Missing church_id in session metadata", {
          session_id: stripe_session_id,
        });
        
        // Update webhook event status to error
        if (supabase) {
          try {
            await supabase
              .from("stripe_webhook_events")
              .update({
                status: "error",
                error_message: "Missing required field: church_id",
              })
              .eq("event_id", event.id);
          } catch (logErr) {
            // Ignore logging errors
          }
        }
        
        return NextResponse.json(
          { error: "Missing required field: church_id" },
          { status: 400 }
        );
      }

      // Get Supabase admin client (if not already initialized)
      if (!supabase) {
        try {
          supabase = getSupabaseAdmin();
        } catch (err: any) {
          console.error("[Stripe Webhook] Failed to initialize Supabase client");
          return NextResponse.json(
            { error: "Server configuration error" },
            { status: 500 }
          );
        }
      }

      // Check global kill switch (log but don't process if paused)
      const globalKillSwitch = process.env.DONATIONS_PAUSED === "true";
      if (globalKillSwitch) {
        console.warn("[Stripe Webhook] Global kill switch is ON - logging event but not processing donation", {
          session_id: stripe_session_id,
          church_id,
        });
        // Still log the webhook event, but don't create donation row
        if (supabase) {
          try {
            await supabase
              .from("stripe_webhook_events")
              .update({
                status: "error",
                error_message: "Donations paused (global kill switch)",
              })
              .eq("event_id", event.id);
          } catch (logErr) {
            // Ignore logging errors
          }
        }
        // Return 200 to acknowledge receipt (don't retry)
        return NextResponse.json({ received: true, paused: true }, { status: 200 });
      }

      // Fetch payment intent to get additional Stripe IDs for reconciliation
      let paymentIntentId: string | null = null;
      let chargeId: string | null = null;
      const transferId: string | null = null;

      try {
        const paymentIntent = session.payment_intent;
        if (paymentIntent && typeof paymentIntent === "string") {
          paymentIntentId = paymentIntent;
          // Fetch payment intent to get charge and transfer IDs
          const pi = await stripe.paymentIntents.retrieve(paymentIntent);
          if (pi.latest_charge && typeof pi.latest_charge === "string") {
            chargeId = pi.latest_charge;
            // Fetch charge to get transfer ID if using destination charges
            try {
              const charge = await stripe.charges.retrieve(pi.latest_charge as string);
              // For destination charges, transfers are automatically created
              // Transfer ID lookup is optional for reconciliation
              // We can query transfers by payment intent ID if needed in the future
            } catch (chargeErr) {
              // Ignore charge retrieval errors (not critical)
              console.warn("[Stripe Webhook] Could not retrieve charge details", chargeErr);
            }
          }
        }
      } catch (piErr) {
        // Ignore payment intent retrieval errors (not critical for donation creation)
        console.warn("[Stripe Webhook] Could not retrieve payment intent details", piErr);
      }

      // Idempotent insert using upsert with conflict resolution
      const { error } = await supabase
        .from("donations")
        .upsert(
          [
            {
              church_id: String(church_id),
              stripe_session_id,
              stripe_payment_intent_id: paymentIntentId,
              stripe_charge_id: chargeId,
              stripe_transfer_id: transferId,
              amount_cents,
              currency,
              status: payment_status,
              donor_email,
              donor_name,
              donor_address: donor_address ? (donor_address as any) : null,
            },
          ],
          {
            onConflict: "stripe_session_id",
          }
        );

      if (error) {
        console.error("[Stripe Webhook] Supabase upsert failed", {
          session_id: stripe_session_id,
        });
        
        // Update webhook event status to error
        try {
          await supabase
            .from("stripe_webhook_events")
            .update({
              status: "error",
              error_message: `Database error: ${error.message}`,
            })
            .eq("event_id", event.id);
        } catch (logErr) {
          // Ignore logging errors
        }
        
        // Return 200 to prevent Stripe from retrying on permanent DB issues
        return NextResponse.json(
          { received: true, error: "Database error" },
          { status: 200 }
        );
      }

      return NextResponse.json({ received: true }, { status: 200 });
    }

    // Handle customer.subscription.updated event
    if (event.type === "customer.subscription.updated") {
      const subscription = event.data.object as Stripe.Subscription;
      const customerId = subscription.customer as string;

      // Get Supabase admin client (if not already initialized)
      if (!supabase) {
        try {
          supabase = getSupabaseAdmin();
        } catch (err: any) {
          console.error("[Stripe Webhook] Failed to initialize Supabase client");
          return NextResponse.json(
            { error: "Server configuration error" },
            { status: 500 }
          );
        }
      }

      // Find church by customer ID
      const { data: church, error: churchError } = await supabase
        .from("churches")
        .select("church_id")
        .eq("stripe_customer_id", customerId)
        .single();

      if (churchError || !church) {
        console.error("[Stripe Webhook] Church not found for customer", {
          customer_id: customerId,
        });
        return NextResponse.json({ received: true, ignored: true }, { status: 200 });
      }

      // Update subscription status
      const updateData: any = {
        subscription_status: subscription.status,
        stripe_subscription_id: subscription.id,
      };

      // Update canceled_at if subscription is canceled
      if (subscription.status === "canceled" && subscription.canceled_at) {
        updateData.subscription_canceled_at = new Date(subscription.canceled_at * 1000).toISOString();
      } else if (subscription.status !== "canceled") {
        updateData.subscription_canceled_at = null;
      }

      // Update started_at if not set and subscription is active
      if (subscription.status === "active" && subscription.created) {
        const { data: existingChurch } = await supabase
          .from("churches")
          .select("subscription_started_at")
          .eq("church_id", church.church_id)
          .single();

        if (!existingChurch?.subscription_started_at) {
          updateData.subscription_started_at = new Date(subscription.created * 1000).toISOString();
        }
      }

      const { error: updateError } = await supabase
        .from("churches")
        .update(updateData)
        .eq("church_id", church.church_id);

      if (updateError) {
        console.error("[Stripe Webhook] Failed to update subscription status", {
          church_id: church.church_id,
          error: updateError.message,
        });
      }

      return NextResponse.json({ received: true }, { status: 200 });
    }

    // Handle customer.subscription.deleted event
    if (event.type === "customer.subscription.deleted") {
      const subscription = event.data.object as Stripe.Subscription;
      const customerId = subscription.customer as string;

      // Get Supabase admin client (if not already initialized)
      if (!supabase) {
        try {
          supabase = getSupabaseAdmin();
        } catch (err: any) {
          console.error("[Stripe Webhook] Failed to initialize Supabase client");
          return NextResponse.json(
            { error: "Server configuration error" },
            { status: 500 }
          );
        }
      }

      // Find church by customer ID
      const { data: church, error: churchError } = await supabase
        .from("churches")
        .select("church_id")
        .eq("stripe_customer_id", customerId)
        .single();

      if (churchError || !church) {
        console.error("[Stripe Webhook] Church not found for customer", {
          customer_id: customerId,
        });
        return NextResponse.json({ received: true, ignored: true }, { status: 200 });
      }

      // Update subscription status to canceled
      const canceledAt = subscription.canceled_at
        ? new Date(subscription.canceled_at * 1000).toISOString()
        : new Date().toISOString();

      const { error: updateError } = await supabase
        .from("churches")
        .update({
          subscription_status: "canceled",
          subscription_canceled_at: canceledAt,
        })
        .eq("church_id", church.church_id);

      if (updateError) {
        console.error("[Stripe Webhook] Failed to update subscription deletion", {
          church_id: church.church_id,
          error: updateError.message,
        });
      }

      return NextResponse.json({ received: true }, { status: 200 });
    }

    // Acknowledge all other event types to prevent retries
    return NextResponse.json({ received: true, ignored: true, type: event.type }, { status: 200 });
  } catch (err: any) {
    console.error("[Stripe Webhook] Unexpected error");
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

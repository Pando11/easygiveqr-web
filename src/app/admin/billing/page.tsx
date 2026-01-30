"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";

interface ChurchBilling {
  church_id: string;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  subscription_status: string | null;
  subscription_started_at: string | null;
  subscription_canceled_at: string | null;
}

export default function BillingPage() {
  const searchParams = useSearchParams();
  const [churchId, setChurchId] = useState("");
  const [churchBilling, setChurchBilling] = useState<ChurchBilling | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [success, setSuccess] = useState<string>("");
  const [checkoutUrl, setCheckoutUrl] = useState<string>("");

  // Check for success/canceled params
  useEffect(() => {
    const successParam = searchParams.get("success");
    const canceledParam = searchParams.get("canceled");
    const churchIdParam = searchParams.get("church_id");

    if (successParam === "true" && churchIdParam) {
      setChurchId(churchIdParam);
      setSuccess("Subscription checkout completed successfully!");
      fetchChurchBilling(churchIdParam);
    } else if (canceledParam === "true" && churchIdParam) {
      setChurchId(churchIdParam);
      setError("Subscription checkout was canceled.");
    }
  }, [searchParams]);

  async function fetchChurchBilling(id: string) {
    try {
      setLoading(true);
      setError("");

      const res = await fetch(`/api/billing/church?church_id=${encodeURIComponent(id)}`, {
        headers: {
          "x-admin-secret": prompt("Enter ADMIN_SECRET:") || "",
        },
      });

      const data = await res.json();

      if (data.ok) {
        setChurchBilling({
          church_id: data.church_id,
          stripe_customer_id: data.stripe_customer_id,
          stripe_subscription_id: data.stripe_subscription_id,
          subscription_status: data.subscription_status,
          subscription_started_at: data.subscription_started_at,
          subscription_canceled_at: data.subscription_canceled_at,
        });
      } else {
        setError(data.error || "Failed to fetch church billing");
      }
    } catch (e: any) {
      setError(e?.message || "Failed to fetch church billing");
    } finally {
      setLoading(false);
    }
  }

  async function createCustomer() {
    if (!churchId) {
      setError("Please enter a church ID");
      return;
    }

    try {
      setLoading(true);
      setError("");
      setSuccess("");

      const res = await fetch("/api/billing/create-customer", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-secret": prompt("Enter ADMIN_SECRET:") || "",
        },
        body: JSON.stringify({ church_id: churchId }),
      });

      const data = await res.json();

      if (data.ok) {
        setSuccess(`Customer created: ${data.stripe_customer_id}`);
        if (data.message) {
          setSuccess(data.message);
        }
        fetchChurchBilling(churchId);
      } else {
        setError(data.error || "Failed to create customer");
      }
    } catch (e: any) {
      setError(e?.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  async function createSubscriptionCheckout() {
    if (!churchId) {
      setError("Please enter a church ID");
      return;
    }

    try {
      setLoading(true);
      setError("");
      setSuccess("");

      const res = await fetch("/api/billing/create-subscription-checkout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-secret": prompt("Enter ADMIN_SECRET:") || "",
        },
        body: JSON.stringify({ church_id: churchId }),
      });

      const data = await res.json();

      if (data.ok && data.url) {
        setCheckoutUrl(data.url);
        setSuccess("Checkout session created. Click the link below to complete subscription.");
        // Optionally open in new window
        // window.open(data.url, '_blank');
      } else {
        setError(data.error || "Failed to create checkout session");
      }
    } catch (e: any) {
      setError(e?.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ padding: 40, fontFamily: "sans-serif", maxWidth: 800 }}>
      <h1>Church Billing Management</h1>
      <p style={{ color: "#666", marginTop: 8 }}>
        Manage Stripe subscriptions for churches ($29.95/month)
      </p>

      {error && (
        <div
          style={{
            marginTop: 24,
            padding: 16,
            background: "#FEE2E2",
            border: "1px solid #FCA5A5",
            borderRadius: 6,
            color: "#991B1B",
          }}
        >
          <strong>Error:</strong> {error}
        </div>
      )}

      {success && (
        <div
          style={{
            marginTop: 24,
            padding: 16,
            background: "#F0FDF4",
            border: "1px solid #86EFAC",
            borderRadius: 6,
            color: "#166534",
          }}
        >
          <strong>Success:</strong> {success}
        </div>
      )}

      {checkoutUrl && (
        <div
          style={{
            marginTop: 24,
            padding: 16,
            background: "#EFF6FF",
            border: "1px solid #93C5FD",
            borderRadius: 6,
          }}
        >
          <p>
            <strong>Checkout Link:</strong>
          </p>
          <a
            href={checkoutUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "inline-block",
              marginTop: 8,
              padding: "12px 24px",
              background: "#1D4ED8",
              color: "white",
              textDecoration: "none",
              borderRadius: 6,
              fontWeight: "bold",
            }}
          >
            Complete Subscription Checkout →
          </a>
        </div>
      )}

      <div style={{ marginTop: 32 }}>
        <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
          Church ID
        </label>
        <input
          type="text"
          value={churchId}
          onChange={(e) => setChurchId(e.target.value)}
          placeholder="EGQR-123"
          style={{
            width: "100%",
            padding: 10,
            fontSize: 16,
            border: "1px solid #ddd",
            borderRadius: 6,
          }}
        />
      </div>

      <div style={{ marginTop: 24, display: "flex", gap: 12, flexWrap: "wrap" }}>
        <button
          onClick={createCustomer}
          disabled={loading || !churchId}
          style={{
            padding: "12px 24px",
            fontSize: 16,
            fontWeight: "bold",
            background: loading || !churchId ? "#9CA3AF" : "#1D4ED8",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: loading || !churchId ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Processing..." : "Create Customer"}
        </button>

        <button
          onClick={createSubscriptionCheckout}
          disabled={loading || !churchId}
          style={{
            padding: "12px 24px",
            fontSize: 16,
            fontWeight: "bold",
            background: loading || !churchId ? "#9CA3AF" : "#059669",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: loading || !churchId ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Processing..." : "Create Subscription Checkout"}
        </button>

        <button
          onClick={() => fetchChurchBilling(churchId)}
          disabled={loading || !churchId}
          style={{
            padding: "12px 24px",
            fontSize: 16,
            fontWeight: "bold",
            background: loading || !churchId ? "#9CA3AF" : "#7C3AED",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: loading || !churchId ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Loading..." : "Refresh Status"}
        </button>
      </div>

      {churchBilling && (
        <div style={{ marginTop: 32, padding: 20, background: "#F9FAFB", borderRadius: 6 }}>
          <h2>Current Subscription Status</h2>
          <div style={{ marginTop: 16 }}>
            <p>
              <strong>Church ID:</strong> {churchBilling.church_id}
            </p>
            <p>
              <strong>Customer ID:</strong> {churchBilling.stripe_customer_id || "Not created"}
            </p>
            <p>
              <strong>Subscription ID:</strong> {churchBilling.stripe_subscription_id || "Not subscribed"}
            </p>
            <p>
              <strong>Status:</strong>{" "}
              <span
                style={{
                  padding: "4px 8px",
                  borderRadius: 4,
                  background:
                    churchBilling.subscription_status === "active"
                      ? "#D1FAE5"
                      : churchBilling.subscription_status === "canceled"
                      ? "#FEE2E2"
                      : "#FEF3C7",
                  color:
                    churchBilling.subscription_status === "active"
                      ? "#065F46"
                      : churchBilling.subscription_status === "canceled"
                      ? "#991B1B"
                      : "#92400E",
                }}
              >
                {churchBilling.subscription_status || "No subscription"}
              </span>
            </p>
            {churchBilling.subscription_started_at && (
              <p>
                <strong>Started:</strong> {new Date(churchBilling.subscription_started_at).toLocaleString()}
              </p>
            )}
            {churchBilling.subscription_canceled_at && (
              <p>
                <strong>Canceled:</strong> {new Date(churchBilling.subscription_canceled_at).toLocaleString()}
              </p>
            )}
          </div>
        </div>
      )}

      <div style={{ marginTop: 32 }}>
        <p style={{ color: "#666", fontSize: 14 }}>
          <strong>Note:</strong> This page requires ADMIN_SECRET authentication. The secret will be prompted
          when you click the buttons above.
        </p>
      </div>
    </main>
  );
}

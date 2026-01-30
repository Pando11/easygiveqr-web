"use client";

import { useSearchParams } from "next/navigation";
import { useState, useEffect } from "react";
import { DONATION_PRESETS, type DonationFrequency } from "@/lib/donationConstants";
import { getDonationTranslations, type Language } from "@/lib/donationTranslations";
import {
  getDonationUnavailableMessage,
  getChurchNotFoundMessage,
  getDonationsPausedMessage,
} from "@/lib/donationMessages";

/**
 * Client-side eligibility check (matches server-side logic)
 */
function isChurchEligibleForDonations(church: {
  status?: string | null;
  subscription_status?: string | null;
  stripe_charges_enabled?: boolean | null;
  stripe_payouts_enabled?: boolean | null;
  donations_paused?: boolean | null;
}): boolean {
  // Check global kill switch (client can't check env, but server will block)
  // Check per-church pause
  if (church.donations_paused === true) {
    return false;
  }

  // Check church status (paused and closed are blocked)
  if (church.status !== "active") {
    return false;
  }

  const validSubscriptionStatuses = ["active", "trialing"];
  if (!church.subscription_status || !validSubscriptionStatuses.includes(church.subscription_status)) {
    return false;
  }

  if (!church.stripe_charges_enabled || !church.stripe_payouts_enabled) {
    return false;
  }

  return true;
}

interface Church {
  church_id: string;
  display_name: string;
  legal_name: string;
  ein: string;
  logo_url: string | null;
  primary_color: string;
  donation_phrase: string;
  preferred_language: "EN" | "ES";
  status: string | null;
  subscription_status: string | null;
  stripe_charges_enabled: boolean | null;
  stripe_payouts_enabled: boolean | null;
  monthly_enabled: boolean | null;
  donations_paused: boolean | null;
}

export default function DonatePage() {
  const searchParams = useSearchParams();
  const churchId = searchParams.get("church_id");
  const [church, setChurch] = useState<Church | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [checkoutLoading, setCheckoutLoading] = useState(false);
  const [selectedAmount, setSelectedAmount] = useState<number>(1000); // Default $10
  const [frequency, setFrequency] = useState<DonationFrequency>("one_time");

  // Reset frequency to one_time if monthly is disabled when church data loads
  useEffect(() => {
    if (church && !church.monthly_enabled && frequency === "monthly") {
      setFrequency("one_time");
    }
  }, [church, frequency]);

  useEffect(() => {
    if (!churchId) {
      setError("missing_church_id");
      setLoading(false);
      return;
    }

    async function fetchChurch() {
      if (!churchId) return;
      try {
        const res = await fetch(`/api/church?church_id=${encodeURIComponent(churchId)}`);
        const data = await res.json();

        if (data.ok && data.church) {
          setChurch(data.church);
        } else {
          setError("church_not_found");
        }
      } catch (e: any) {
        setError("network_error");
      } finally {
        setLoading(false);
      }
    }

    fetchChurch();
  }, [churchId]);

  async function startCheckout() {
    if (!churchId || !church) {
      return;
    }

    setCheckoutLoading(true);

    try {
      const res = await fetch("/api/checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          church_id: churchId,
          amount_cents: selectedAmount,
          frequency: frequency,
        }),
      });

      const data = await res.json();

      if (data?.url) {
        window.location.href = data.url;
      } else {
        alert(data?.error || "Checkout failed");
        setCheckoutLoading(false);
      }
    } catch (e: any) {
      alert("Network error. Please try again.");
      setCheckoutLoading(false);
    }
  }

  // Get translations based on church language
  const language: Language = church?.preferred_language || "EN";
  const t = getDonationTranslations(language);

  // Loading state
  if (loading) {
    return (
      <main
        style={{
          padding: 40,
          fontFamily: "sans-serif",
          textAlign: "center",
          maxWidth: 600,
          margin: "0 auto",
        }}
      >
        <p>{t.loading}</p>
      </main>
    );
  }

  // Error: Missing church_id
  if (error === "missing_church_id") {
    const message = getChurchNotFoundMessage(language);
    return (
      <main
        style={{
          padding: 40,
          fontFamily: "sans-serif",
          maxWidth: 600,
          margin: "0 auto",
        }}
      >
        <h1 style={{ color: "#DC2626" }}>{message.title}</h1>
        <p style={{ color: "#666", marginTop: 16 }}>{message.message}</p>
      </main>
    );
  }

  // Error: Church not found
  if (error === "church_not_found" || !church) {
    const message = getChurchNotFoundMessage(language);
    return (
      <main
        style={{
          padding: 40,
          fontFamily: "sans-serif",
          maxWidth: 600,
          margin: "0 auto",
        }}
      >
        <h1 style={{ color: "#DC2626" }}>{message.title}</h1>
        <p style={{ color: "#666", marginTop: 16 }}>{message.message}</p>
      </main>
    );
  }

  // Check eligibility
  const isEligible = isChurchEligibleForDonations(church);
  
  // Determine specific message based on reason
  let unavailableMessage;
  if (church.donations_paused === true) {
    unavailableMessage = getDonationsPausedMessage(language);
  } else {
    unavailableMessage = getDonationUnavailableMessage(language);
  }

  // Not eligible: Show message, don't show form
  if (!isEligible) {
    return (
      <main
        style={{
          padding: 40,
          fontFamily: "sans-serif",
          maxWidth: 600,
          margin: "0 auto",
          textAlign: "center",
        }}
      >
        <h1 style={{ color: "#DC2626", marginBottom: 16 }}>{unavailableMessage.title}</h1>
        <p style={{ color: "#666", fontSize: 16, lineHeight: 1.6 }}>{unavailableMessage.message}</p>
        {church.display_name && (
          <p style={{ color: "#999", marginTop: 24, fontSize: 14 }}>{church.display_name}</p>
        )}
      </main>
    );
  }

  // Format amount for display
  const formatAmount = (cents: number) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(cents / 100);
  };

  const primaryColor = church.primary_color || "#1D4ED8";

  // Eligible: Show donation form
  return (
    <main
      style={{
        padding: "24px 20px",
        fontFamily: "sans-serif",
        maxWidth: 600,
        margin: "0 auto",
      }}
    >
      {/* Church Logo */}
      {church.logo_url && (
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <img
            src={church.logo_url}
            alt={church.display_name}
            style={{
              maxWidth: 200,
              maxHeight: 100,
              objectFit: "contain",
            }}
          />
        </div>
      )}

      {/* Church Name */}
      <h1
        style={{
          textAlign: "center",
          marginBottom: 8,
          fontSize: 28,
          fontWeight: "bold",
          color: "#1F2937",
        }}
      >
        {church.display_name || church.legal_name}
      </h1>

      {/* Donation Phrase */}
      {church.donation_phrase && (
        <p
          style={{
            textAlign: "center",
            color: "#666",
            fontSize: 16,
            marginBottom: 32,
            lineHeight: 1.6,
          }}
        >
          {church.donation_phrase}
        </p>
      )}

      {/* Amount Selection */}
      <div style={{ marginBottom: 32 }}>
        <label
          style={{
            display: "block",
            fontSize: 14,
            fontWeight: "600",
            color: "#374151",
            marginBottom: 12,
          }}
        >
          {t.selectAmount}
        </label>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gap: 12,
          }}
        >
          {DONATION_PRESETS.map((amount) => (
            <button
              key={amount}
              onClick={() => setSelectedAmount(amount)}
              disabled={checkoutLoading}
              style={{
                padding: "16px",
                fontSize: 16,
                fontWeight: "600",
                border: `2px solid ${selectedAmount === amount ? primaryColor : "#E5E7EB"}`,
                borderRadius: 8,
                background: selectedAmount === amount ? primaryColor : "white",
                color: selectedAmount === amount ? "white" : "#374151",
                cursor: checkoutLoading ? "not-allowed" : "pointer",
                transition: "all 0.2s",
              }}
            >
              {formatAmount(amount)}
            </button>
          ))}
        </div>
      </div>

      {/* Frequency Toggle - Only show if monthly is enabled */}
      {church.monthly_enabled && (
        <div style={{ marginBottom: 32 }}>
          <label
            style={{
              display: "block",
              fontSize: 14,
              fontWeight: "600",
              color: "#374151",
              marginBottom: 12,
            }}
          >
            {t.frequency}
          </label>
          <div
            style={{
              display: "flex",
              gap: 12,
              background: "#F3F4F6",
              padding: 4,
              borderRadius: 8,
            }}
          >
            <button
              onClick={() => setFrequency("one_time")}
              disabled={checkoutLoading}
              style={{
                flex: 1,
                padding: "12px",
                fontSize: 15,
                fontWeight: "600",
                border: "none",
                borderRadius: 6,
                background: frequency === "one_time" ? "white" : "transparent",
                color: frequency === "one_time" ? "#374151" : "#6B7280",
                cursor: checkoutLoading ? "not-allowed" : "pointer",
                boxShadow: frequency === "one_time" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                transition: "all 0.2s",
              }}
            >
              {t.oneTime}
            </button>
            <button
              onClick={() => setFrequency("monthly")}
              disabled={checkoutLoading}
              style={{
                flex: 1,
                padding: "12px",
                fontSize: 15,
                fontWeight: "600",
                border: "none",
                borderRadius: 6,
                background: frequency === "monthly" ? "white" : "transparent",
                color: frequency === "monthly" ? "#374151" : "#6B7280",
                cursor: checkoutLoading ? "not-allowed" : "pointer",
                boxShadow: frequency === "monthly" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                transition: "all 0.2s",
              }}
            >
              {t.monthly}
            </button>
          </div>
        </div>
      )}

      {/* Donate Button */}
      <button
        onClick={startCheckout}
        disabled={checkoutLoading}
        style={{
          width: "100%",
          padding: "16px",
          fontSize: 18,
          fontWeight: "bold",
          background: primaryColor,
          color: "white",
          border: "none",
          borderRadius: 8,
          cursor: checkoutLoading ? "not-allowed" : "pointer",
          opacity: checkoutLoading ? 0.7 : 1,
          transition: "opacity 0.2s",
        }}
      >
        {checkoutLoading
          ? language === "ES"
            ? "Redirigiendo…"
            : "Redirecting…"
          : `${t.donateButton} ${formatAmount(selectedAmount)}${frequency === "monthly" ? " / " + (language === "ES" ? "mes" : "month") : ""}`}
      </button>
    </main>
  );
}

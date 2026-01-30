"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { getDonationTranslations, type Language } from "@/lib/donationTranslations";
import { getDonationTimeoutMessage } from "@/lib/donationMessages";

interface Donation {
  church_id: string;
  stripe_session_id: string;
  amount_cents: number;
  currency: string;
  status: string;
  created_at: string;
}

interface Church {
  preferred_language: "EN" | "ES";
  display_name: string;
}

export default function SuccessPage() {
  const searchParams = useSearchParams();
  const [donation, setDonation] = useState<Donation | null>(null);
  const [church, setChurch] = useState<Church | null>(null);
  const [status, setStatus] = useState<"loading" | "found" | "not_found" | "error">("loading");
  const [error, setError] = useState<string>("");
  const [retryCount, setRetryCount] = useState(0);

  const church_id = useMemo(() => searchParams.get("church_id") || "", [searchParams]);
  const session_id = useMemo(() => searchParams.get("session_id") || "", [searchParams]);

  const maxRetries = 10; // 10 retries × 3 seconds = 30 seconds max
  const retryInterval = 3000; // 3 seconds

  // Fetch church for language
  useEffect(() => {
    if (!church_id) return;

    async function fetchChurch() {
      try {
        const res = await fetch(`/api/church?church_id=${encodeURIComponent(church_id)}`);
        const data = await res.json();
        if (data.ok && data.church) {
          setChurch(data.church);
        }
      } catch (e) {
        // Ignore errors - use default language
      }
    }

    fetchChurch();
  }, [church_id]);

  useEffect(() => {
    async function fetchDonation() {
      if (!session_id) {
        setStatus("error");
        setError("Missing session_id");
        return;
      }

      try {
        const res = await fetch(`/api/donation?session_id=${encodeURIComponent(session_id)}`);
        const data = await res.json();

        if (res.status === 200 && data?.ok && data?.donation) {
          setDonation(data.donation);
          setStatus("found");
          setError("");
        } else if (res.status === 404) {
          // Not found yet - webhook may not have processed
          setStatus("not_found");
          setError("");
        } else {
          setStatus("error");
          setError(data?.error || `HTTP ${res.status}`);
        }
      } catch (e: any) {
        setStatus("error");
        setError(e?.message || "Network error");
      }
    }

    // Initial fetch
    fetchDonation();
  }, [session_id]);

  // Auto-retry logic for not_found status
  useEffect(() => {
    if (status !== "not_found" || retryCount >= maxRetries) return;

    const timer = setTimeout(async () => {
      if (!session_id) return;

      try {
        const res = await fetch(`/api/donation?session_id=${encodeURIComponent(session_id)}`);
        const data = await res.json();

        if (res.status === 200 && data?.ok && data?.donation) {
          setDonation(data.donation);
          setStatus("found");
          setError("");
        } else {
          // Still not found, increment retry count
          setRetryCount((prev) => prev + 1);
        }
      } catch (e: any) {
        // On error, stop retrying
        setStatus("error");
        setError(e?.message || "Network error");
      }
    }, retryInterval);

    return () => clearTimeout(timer);
  }, [status, retryCount, session_id]);

  const handleRetry = () => {
    setRetryCount(0);
    setStatus("loading");
    if (session_id) {
      fetch(`/api/donation?session_id=${encodeURIComponent(session_id)}`)
        .then((res) => {
          return res.json().then((data) => {
            if (res.status === 200 && data?.ok && data?.donation) {
              setDonation(data.donation);
              setStatus("found");
            } else {
              setStatus("not_found");
            }
          });
        })
        .catch(() => {
          setStatus("error");
        });
    }
  };

  // Get translations
  const language: Language = church?.preferred_language || "EN";
  const t = getDonationTranslations(language);

  const formatAmount = (cents: number, currency: string) => {
    const amount = (cents / 100).toFixed(2);
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency.toUpperCase(),
    }).format(parseFloat(amount));
  };

  return (
    <main
      style={{
        padding: 40,
        fontFamily: "sans-serif",
        maxWidth: 600,
        margin: "0 auto",
      }}
    >
      <h1 style={{ marginBottom: 24 }}>
        {status === "found" ? t.donationVerified : t.paymentReceived}
      </h1>

      {status === "loading" && <p>{t.verifying}</p>}

      {status === "not_found" && (
        <>
          {retryCount < maxRetries ? (
            <>
              <p>{t.paymentReceived}</p>
              <p style={{ fontSize: 14, opacity: 0.7, marginTop: 8 }}>
                {t.retrying} ({retryCount + 1}/{maxRetries})
              </p>
              <div style={{ marginTop: 16 }}>
                <button
                  onClick={handleRetry}
                  style={{
                    padding: "10px 20px",
                    fontSize: 14,
                    background: "#1D4ED8",
                    color: "white",
                    border: "none",
                    borderRadius: 6,
                    cursor: "pointer",
                  }}
                >
                  {t.retryButton}
                </button>
              </div>
            </>
          ) : (
            <>
              {/* Timeout: Show friendly message after max retries */}
              {(() => {
                const timeoutMsg = getDonationTimeoutMessage(language);
                return (
                  <>
                    <h1 style={{ color: "#10B981", marginBottom: 16 }}>{timeoutMsg.title}</h1>
                    <p style={{ color: "#666", fontSize: 16, lineHeight: 1.6 }}>{timeoutMsg.message}</p>
                    {church?.display_name && (
                      <p style={{ color: "#999", marginTop: 24, fontSize: 14 }}>{church.display_name}</p>
                    )}
                  </>
                );
              })()}
            </>
          )}
        </>
      )}

      {status === "error" && (
        <>
          <h1 style={{ color: "#DC2626", marginBottom: 16 }}>
            {language === "ES" ? "Error" : "Error"}
          </h1>
          <p style={{ color: "#666", fontSize: 16, lineHeight: 1.6 }}>
            {language === "ES"
              ? "Ocurrió un error al verificar su donación. Por favor, póngase en contacto con la iglesia si necesita ayuda."
              : "An error occurred while verifying your donation. Please contact the church if you need help."}
          </p>
        </>
      )}

      {status === "found" && donation && (
        <>
          <p style={{ color: "green", fontWeight: "bold", marginTop: 16 }}>{t.donationVerified}</p>

          <div style={{ marginTop: 24, padding: 16, background: "#f5f5f5", borderRadius: 8 }}>
            <p>
              <strong>{t.amount}:</strong> {formatAmount(donation.amount_cents, donation.currency)}
            </p>
            <p>
              <strong>{t.currency}:</strong> {donation.currency.toUpperCase()}
            </p>
            <p>
              <strong>{t.status}:</strong> {donation.status}
            </p>
            {donation.created_at && (
              <p style={{ fontSize: 12, opacity: 0.7, marginTop: 8 }}>
                {t.processed}: {new Date(donation.created_at).toLocaleString()}
              </p>
            )}
          </div>
        </>
      )}

      <div style={{ marginTop: 24 }}>
        <Link
          href={church_id ? `/donate?church_id=${encodeURIComponent(church_id)}` : "/donate"}
          style={{
            color: "#1D4ED8",
            textDecoration: "underline",
          }}
        >
          {t.backToDonate}
        </Link>
      </div>
    </main>
  );
}

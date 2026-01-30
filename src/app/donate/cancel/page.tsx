"use client";

import { useSearchParams } from "next/navigation";
import { useState, useEffect } from "react";
import Link from "next/link";
import { getDonationTranslations, type Language } from "@/lib/donationTranslations";

interface Church {
  preferred_language: "EN" | "ES";
  display_name: string;
}

export default function DonateCancelPage() {
  const searchParams = useSearchParams();
  const churchId = searchParams.get("church_id") || "";
  const [church, setChurch] = useState<Church | null>(null);
  const [loading, setLoading] = useState(true);

  // Fetch church for language
  useEffect(() => {
    if (!churchId) {
      setLoading(false);
      return;
    }

    async function fetchChurch() {
      try {
        const res = await fetch(`/api/church?church_id=${encodeURIComponent(churchId)}`);
        const data = await res.json();
        if (data.ok && data.church) {
          setChurch(data.church);
        }
      } catch (e) {
        // Ignore errors - use default language
      } finally {
        setLoading(false);
      }
    }

    fetchChurch();
  }, [churchId]);

  // Get translations
  const language: Language = church?.preferred_language || "EN";
  const t = getDonationTranslations(language);

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
      <h1 style={{ marginBottom: 16 }}>{t.donationCanceled}</h1>
      <p style={{ color: "#666", marginBottom: 24 }}>{t.noPaymentCompleted}</p>

      <div style={{ marginTop: 24 }}>
        <Link
          href={churchId ? `/donate?church_id=${encodeURIComponent(churchId)}` : "/donate"}
          style={{
            color: "#1D4ED8",
            textDecoration: "underline",
            fontSize: 16,
          }}
        >
          {t.backToDonateCancel}
        </Link>
      </div>
    </main>
  );
}

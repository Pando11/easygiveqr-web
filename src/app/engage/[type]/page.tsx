"use client";

import { useSearchParams, useParams } from "next/navigation";
import { useState, useEffect } from "react";
import Link from "next/link";
import { getEngagementTranslations, type EngagementType } from "@/lib/engagementTranslations";

interface Church {
  church_id: string;
  display_name: string;
  logo_url: string | null;
  primary_color: string;
  donation_phrase: string | null;
  preferred_language: "EN" | "ES";
}

export default function EngagementPage() {
  const searchParams = useSearchParams();
  const params = useParams();
  const type = params.type as EngagementType;

  const churchId = searchParams.get("church_id");
  const [church, setChurch] = useState<Church | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Form state
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState(""); // Honey pot field (hidden)

  useEffect(() => {
    if (!churchId) {
      setError("missing_church_id");
      setLoading(false);
      return;
    }

    async function fetchChurch() {
      try {
        if (!churchId) return;
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

  // Validate type (after all hooks)
  const validTypes: EngagementType[] = ["prayer", "visitor", "volunteer"];
  if (!type || !validTypes.includes(type)) {
    return (
      <main style={{ padding: 40, fontFamily: "sans-serif", textAlign: "center" }}>
        <h1 style={{ color: "#DC2626" }}>Invalid Form Type</h1>
        <p>The form type must be prayer, visitor, or volunteer.</p>
      </main>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    // Validation
    if (type === "prayer") {
      if (!message.trim()) {
        alert(t.errorMissingFields);
        return;
      }
    } else if (type === "visitor" || type === "volunteer") {
      if (!name.trim()) {
        alert(t.errorMissingFields);
        return;
      }
    }

    setSubmitting(true);

    // Honey pot check: if website field is filled, reject silently
    if (website.trim()) {
      // Bot detected - return success but don't submit
      setSubmitted(true);
      setSubmitting(false);
      return;
    }

    try {
      const res = await fetch("/api/engagement/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          church_id: churchId,
          type,
          name: name.trim() || null,
          email: email.trim() || null,
          phone: phone.trim() || null,
          message: message.trim() || null,
        }),
      });

      const data = await res.json();

      if (data.ok) {
        setSubmitted(true);
      } else {
        alert(data.error || t.errorGeneric);
        setSubmitting(false);
      }
    } catch (e: any) {
      alert(t.errorGeneric);
      setSubmitting(false);
    }
  }

  // Get translations
  const language = church?.preferred_language || "EN";
  const t = getEngagementTranslations(language);

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
        <p>{t.submitting}</p>
      </main>
    );
  }

  // Error states
  if (error === "missing_church_id" || error === "church_not_found" || !church) {
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
        <h1 style={{ color: "#DC2626" }}>Church Not Found</h1>
        <p style={{ color: "#666", marginTop: 16 }}>
          {error === "missing_church_id"
            ? "Missing church ID in URL."
            : "The church could not be found."}
        </p>
      </main>
    );
  }

  const primaryColor = church.primary_color || "#1D4ED8";

  // Submitted confirmation
  if (submitted) {
    const submittedTitle =
      type === "prayer" ? t.prayerSubmittedTitle : type === "visitor" ? t.visitorSubmittedTitle : t.volunteerSubmittedTitle;
    const submittedMessage =
      type === "prayer"
        ? t.prayerSubmittedMessage
        : type === "visitor"
        ? t.visitorSubmittedMessage
        : t.volunteerSubmittedMessage;

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
        <h1 style={{ color: "#10B981", marginBottom: 16 }}>{submittedTitle}</h1>
        <p style={{ color: "#666", fontSize: 16, lineHeight: 1.6, marginBottom: 32 }}>{submittedMessage}</p>
        <Link
          href={`/donate?church_id=${encodeURIComponent(churchId || "")}`}
          style={{
            display: "inline-block",
            padding: "12px 24px",
            background: primaryColor,
            color: "white",
            textDecoration: "none",
            borderRadius: 8,
            fontWeight: "600",
          }}
        >
          {t.backToChurch}
        </Link>
      </main>
    );
  }

  // Form fields based on type
  const title = type === "prayer" ? t.prayerTitle : type === "visitor" ? t.visitorTitle : t.volunteerTitle;
  const subtitle = type === "prayer" ? t.prayerSubtitle : type === "visitor" ? t.visitorSubtitle : t.volunteerSubtitle;
  const nameLabel = type === "prayer" ? t.prayerNameLabel : type === "visitor" ? t.visitorNameLabel : t.volunteerNameLabel;
  const nameRequired = type === "visitor" || type === "volunteer";
  const messageLabel =
    type === "prayer" ? t.prayerMessageLabel : type === "visitor" ? t.visitorMessageLabel : t.volunteerMessageLabel;
  const messagePlaceholder =
    type === "prayer"
      ? t.prayerMessagePlaceholder
      : type === "visitor"
      ? t.visitorMessagePlaceholder
      : t.volunteerMessagePlaceholder;
  const messageRequired = type === "prayer";
  const submitButton =
    type === "prayer" ? t.prayerSubmitButton : type === "visitor" ? t.visitorSubmitButton : t.volunteerSubmitButton;

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

      {/* Title */}
      <h1
        style={{
          textAlign: "center",
          marginBottom: 8,
          fontSize: 28,
          fontWeight: "bold",
          color: "#1F2937",
        }}
      >
        {title}
      </h1>

      {/* Subtitle */}
      <p
        style={{
          textAlign: "center",
          color: "#666",
          fontSize: 16,
          marginBottom: 32,
          lineHeight: 1.6,
        }}
      >
        {subtitle}
      </p>

        {/* Form */}
      <form onSubmit={handleSubmit}>
        {/* Honey pot field (hidden) */}
        <input
          type="text"
          name="website"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          style={{
            position: "absolute",
            left: "-9999px",
            opacity: 0,
            pointerEvents: "none",
          }}
          tabIndex={-1}
          aria-hidden="true"
          autoComplete="off"
        />
        {/* Name */}
        <div style={{ marginBottom: 20 }}>
          <label
            style={{
              display: "block",
              fontSize: 14,
              fontWeight: "600",
              color: "#374151",
              marginBottom: 8,
            }}
          >
            {nameLabel} {nameRequired ? <span style={{ color: "#DC2626" }}>*</span> : `(${t.optional})`}
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required={nameRequired}
            style={{
              width: "100%",
              padding: "12px",
              fontSize: 16,
              border: "1px solid #D1D5DB",
              borderRadius: 8,
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* Email */}
        <div style={{ marginBottom: 20 }}>
          <label
            style={{
              display: "block",
              fontSize: 14,
              fontWeight: "600",
              color: "#374151",
              marginBottom: 8,
            }}
          >
            {type === "prayer" ? t.prayerEmailLabel : type === "visitor" ? t.visitorEmailLabel : t.volunteerEmailLabel}{" "}
            ({t.optional})
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={{
              width: "100%",
              padding: "12px",
              fontSize: 16,
              border: "1px solid #D1D5DB",
              borderRadius: 8,
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* Phone */}
        <div style={{ marginBottom: 20 }}>
          <label
            style={{
              display: "block",
              fontSize: 14,
              fontWeight: "600",
              color: "#374151",
              marginBottom: 8,
            }}
          >
            {type === "prayer" ? t.prayerPhoneLabel : type === "visitor" ? t.visitorPhoneLabel : t.volunteerPhoneLabel}{" "}
            ({t.optional})
          </label>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            style={{
              width: "100%",
              padding: "12px",
              fontSize: 16,
              border: "1px solid #D1D5DB",
              borderRadius: 8,
              boxSizing: "border-box",
            }}
          />
        </div>

        {/* Message */}
        <div style={{ marginBottom: 24 }}>
          <label
            style={{
              display: "block",
              fontSize: 14,
              fontWeight: "600",
              color: "#374151",
              marginBottom: 8,
            }}
          >
            {messageLabel} {messageRequired ? <span style={{ color: "#DC2626" }}>*</span> : `(${t.optional})`}
          </label>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            required={messageRequired}
            placeholder={messagePlaceholder}
            rows={6}
            style={{
              width: "100%",
              padding: "12px",
              fontSize: 16,
              border: "1px solid #D1D5DB",
              borderRadius: 8,
              boxSizing: "border-box",
              fontFamily: "inherit",
              resize: "vertical",
            }}
          />
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={submitting}
          style={{
            width: "100%",
            padding: "16px",
            fontSize: 18,
            fontWeight: "bold",
            background: primaryColor,
            color: "white",
            border: "none",
            borderRadius: 8,
            cursor: submitting ? "not-allowed" : "pointer",
            opacity: submitting ? 0.7 : 1,
            transition: "opacity 0.2s",
          }}
        >
          {submitting ? t.submitting : submitButton}
        </button>
      </form>
    </main>
  );
}

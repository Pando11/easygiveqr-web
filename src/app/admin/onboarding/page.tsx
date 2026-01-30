"use client";

import { useState } from "react";

interface OnboardingResult {
  ok: boolean;
  church_id?: string;
  donate_url?: string;
  logo_url?: string;
  qr_code_url?: string;
  stripe_account_id?: string;
  onboarding_link?: string;
  error?: string;
}

export default function OnboardingPage() {
  const [formData, setFormData] = useState({
    church_id: "",
    legal_name: "",
    display_name: "",
    ein: "",
    preferred_language: "EN",
    primary_color: "#1D4ED8",
    donation_phrase: "",
    admin_emails: "",
  });

  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OnboardingResult | null>(null);
  const [error, setError] = useState<string>("");

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] || null;
    setLogoFile(file);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);

    try {
      // Create FormData
      const formDataToSend = new FormData();
      formDataToSend.append("church_id", formData.church_id);
      formDataToSend.append("legal_name", formData.legal_name);
      formDataToSend.append("display_name", formData.display_name);
      formDataToSend.append("ein", formData.ein);
      formDataToSend.append("preferred_language", formData.preferred_language);
      formDataToSend.append("primary_color", formData.primary_color);
      formDataToSend.append("donation_phrase", formData.donation_phrase);
      formDataToSend.append("admin_emails", formData.admin_emails);

      if (!logoFile) {
        setError("Please select a logo file");
        setLoading(false);
        return;
      }

      formDataToSend.append("logo", logoFile);

      // Submit to API
      const res = await fetch("/api/onboarding/create-church", {
        method: "POST",
        body: formDataToSend,
      });

      const data: OnboardingResult = await res.json();

      if (data.ok) {
        setResult(data);
      } else {
        setError(data.error || "Failed to create church");
      }
    } catch (e: any) {
      setError(e?.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ padding: 40, fontFamily: "sans-serif", maxWidth: 800 }}>
      <h1>Church Onboarding</h1>
      <p style={{ color: "#666", marginTop: 8 }}>
        Create a new church and provision everything needed for launch.
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

      {result?.ok && (
        <div
          style={{
            marginTop: 24,
            padding: 24,
            background: "#F0FDF4",
            border: "1px solid #86EFAC",
            borderRadius: 6,
          }}
        >
          <h2 style={{ marginTop: 0, color: "#166534" }}>✓ Church Created Successfully!</h2>

          <div style={{ marginTop: 16 }}>
            <p>
              <strong>Church ID:</strong> {result.church_id}
            </p>
            <p>
              <strong>Donation URL:</strong>{" "}
              <a href={result.donate_url} target="_blank" rel="noopener noreferrer">
                {result.donate_url}
              </a>
            </p>
            {result.logo_url && (
              <p>
                <strong>Logo URL:</strong>{" "}
                <a href={result.logo_url} target="_blank" rel="noopener noreferrer">
                  {result.logo_url}
                </a>
              </p>
            )}
            {result.qr_code_url && (
              <div style={{ marginTop: 16 }}>
                <p>
                  <strong>QR Code:</strong>
                </p>
                <img
                  src={result.qr_code_url}
                  alt={`QR code for ${result.church_id}`}
                  style={{ maxWidth: 300, height: "auto", marginTop: 8, border: "1px solid #ddd", padding: 8, background: "white" }}
                />
              </div>
            )}
            {result.stripe_account_id && (
              <p style={{ marginTop: 16 }}>
                <strong>Stripe Account ID:</strong> {result.stripe_account_id}
              </p>
            )}
            {result.onboarding_link && (
              <div style={{ marginTop: 16 }}>
                <a
                  href={result.onboarding_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: "inline-block",
                    padding: "12px 24px",
                    background: "#1D4ED8",
                    color: "white",
                    textDecoration: "none",
                    borderRadius: 6,
                    fontWeight: "bold",
                  }}
                >
                  Complete Stripe Onboarding →
                </a>
              </div>
            )}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} style={{ marginTop: 32 }}>
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Church ID <span style={{ color: "red" }}>*</span>
          </label>
          <input
            type="text"
            name="church_id"
            value={formData.church_id}
            onChange={handleInputChange}
            placeholder="EGQR-123"
            required
            pattern="^EGQR-[A-Z0-9]+$"
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
            }}
          />
          <small style={{ color: "#666", display: "block", marginTop: 4 }}>
            Format: EGQR-XXX (e.g., EGQR-123)
          </small>
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Legal Name <span style={{ color: "red" }}>*</span>
          </label>
          <input
            type="text"
            name="legal_name"
            value={formData.legal_name}
            onChange={handleInputChange}
            required
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
            }}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Display Name <span style={{ color: "red" }}>*</span>
          </label>
          <input
            type="text"
            name="display_name"
            value={formData.display_name}
            onChange={handleInputChange}
            required
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
            }}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            EIN <span style={{ color: "red" }}>*</span>
          </label>
          <input
            type="text"
            name="ein"
            value={formData.ein}
            onChange={handleInputChange}
            required
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
            }}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Preferred Language <span style={{ color: "red" }}>*</span>
          </label>
          <select
            name="preferred_language"
            value={formData.preferred_language}
            onChange={handleInputChange}
            required
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
            }}
          >
            <option value="EN">English</option>
            <option value="ES">Spanish</option>
          </select>
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Primary Color <span style={{ color: "red" }}>*</span>
          </label>
          <input
            type="color"
            name="primary_color"
            value={formData.primary_color}
            onChange={handleInputChange}
            required
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
              height: 50,
            }}
          />
          <small style={{ color: "#666", display: "block", marginTop: 4 }}>
            Current: {formData.primary_color}
          </small>
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Donation Phrase <span style={{ color: "red" }}>*</span>
          </label>
          <textarea
            name="donation_phrase"
            value={formData.donation_phrase}
            onChange={handleInputChange}
            required
            rows={3}
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
              fontFamily: "inherit",
            }}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Admin Emails <span style={{ color: "red" }}>*</span>
          </label>
          <textarea
            name="admin_emails"
            value={formData.admin_emails}
            onChange={handleInputChange}
            required
            placeholder="admin@example.com, finance@example.com"
            rows={3}
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
              fontFamily: "inherit",
            }}
          />
          <small style={{ color: "#666", display: "block", marginTop: 4 }}>
            Comma-separated email addresses
          </small>
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: "bold" }}>
            Logo <span style={{ color: "red" }}>*</span>
          </label>
          <input
            type="file"
            accept="image/png,image/jpeg,image/jpg,image/svg+xml,image/webp"
            onChange={handleFileChange}
            required
            style={{
              width: "100%",
              padding: 10,
              fontSize: 16,
              border: "1px solid #ddd",
              borderRadius: 6,
            }}
          />
          <small style={{ color: "#666", display: "block", marginTop: 4 }}>
            PNG, JPG, SVG, or WebP (max 5MB)
            {logoFile && ` - Selected: ${logoFile.name} (${(logoFile.size / 1024).toFixed(1)} KB)`}
          </small>
        </div>

        <button
          type="submit"
          disabled={loading}
          style={{
            padding: "14px 28px",
            fontSize: 16,
            fontWeight: "bold",
            background: loading ? "#9CA3AF" : "#1D4ED8",
            color: "white",
            border: "none",
            borderRadius: 6,
            cursor: loading ? "not-allowed" : "pointer",
            width: "100%",
          }}
        >
          {loading ? "Creating Church..." : "Create Church & Provision Everything"}
        </button>
      </form>
    </main>
  );
}

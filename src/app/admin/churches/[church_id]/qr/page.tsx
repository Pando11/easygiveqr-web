"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

interface QRData {
  church_id: string;
  donate_url: string;
  qr_code_url: string | null;
}

export default function QRCodePage() {
  const params = useParams();
  const churchId = params?.church_id as string;
  const [qrData, setQrData] = useState<QRData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (churchId) {
      fetchQRData();
    }
  }, [churchId]);

  async function fetchQRData() {
    try {
      setLoading(true);
      const res = await fetch(`/api/qr?church_id=${encodeURIComponent(churchId)}`);
      const data = await res.json();

      if (data.ok) {
        setQrData(data);
        setError("");
      } else {
        setError(data.error || "Failed to fetch QR code");
      }
    } catch (e: any) {
      setError(e?.message || "Network error");
    } finally {
      setLoading(false);
    }
  }

  async function generateQR() {
    try {
      setGenerating(true);
      const res = await fetch("/api/qr/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ church_id: churchId, force: true }),
      });

      const data = await res.json();

      if (data.ok) {
        setQrData((prev) => ({
          ...prev!,
          qr_code_url: data.qr_code_url,
        }));
        setError("");
      } else {
        setError(data.error || "Failed to generate QR code");
      }
    } catch (e: any) {
      setError(e?.message || "Network error");
    } finally {
      setGenerating(false);
    }
  }

  function downloadQR() {
    if (!qrData?.qr_code_url) return;

    const link = document.createElement("a");
    link.href = qrData.qr_code_url;
    link.download = `qr-${churchId}.png`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  if (loading) {
    return (
      <main style={{ padding: 40, fontFamily: "sans-serif" }}>
        <p>Loading...</p>
      </main>
    );
  }

  return (
    <main style={{ padding: 40, fontFamily: "sans-serif", maxWidth: 800 }}>
      <h1>QR Code - {churchId}</h1>

      {error && (
        <p style={{ color: "tomato", marginTop: 16 }}>Error: {error}</p>
      )}

      {qrData && (
        <>
          <div style={{ marginTop: 24 }}>
            <p><strong>Donation URL:</strong></p>
            <p style={{ wordBreak: "break-all", opacity: 0.8 }}>
              {qrData.donate_url}
            </p>
          </div>

          {qrData.qr_code_url ? (
            <div style={{ marginTop: 32 }}>
              <h2>QR Code</h2>
              <div style={{ marginTop: 16, padding: 20, background: "#f5f5f5", borderRadius: 8, display: "inline-block" }}>
                <img
                  src={qrData.qr_code_url}
                  alt={`QR code for ${churchId}`}
                  style={{ maxWidth: 400, height: "auto" }}
                />
              </div>

              <div style={{ marginTop: 16 }}>
                <button
                  onClick={downloadQR}
                  style={{
                    padding: "12px 24px",
                    fontSize: 16,
                    background: "#1D4ED8",
                    color: "white",
                    border: "none",
                    borderRadius: 6,
                    cursor: "pointer",
                    marginRight: 12,
                  }}
                >
                  Download PNG
                </button>

                <button
                  onClick={generateQR}
                  disabled={generating}
                  style={{
                    padding: "12px 24px",
                    fontSize: 16,
                    background: "#059669",
                    color: "white",
                    border: "none",
                    borderRadius: 6,
                    cursor: generating ? "not-allowed" : "pointer",
                    opacity: generating ? 0.6 : 1,
                  }}
                >
                  {generating ? "Regenerating..." : "Regenerate QR Code"}
                </button>
              </div>
            </div>
          ) : (
            <div style={{ marginTop: 32 }}>
              <p>No QR code generated yet.</p>
              <button
                onClick={generateQR}
                disabled={generating}
                style={{
                  padding: "12px 24px",
                  fontSize: 16,
                  background: "#1D4ED8",
                  color: "white",
                  border: "none",
                  borderRadius: 6,
                  cursor: generating ? "not-allowed" : "pointer",
                  marginTop: 16,
                }}
              >
                {generating ? "Generating..." : "Generate QR Code"}
              </button>
            </div>
          )}
        </>
      )}

      <div style={{ marginTop: 32 }}>
        <a
          href={`/admin/churches/${churchId}`}
          style={{ color: "#1D4ED8", textDecoration: "underline" }}
        >
          ← Back to church
        </a>
      </div>
    </main>
  );
}

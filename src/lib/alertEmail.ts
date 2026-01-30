/**
 * Critical failure email alerts
 * Throttled to prevent spam (max once per hour per failure type)
 */

import { sendEmail } from "./email/sendEmail";

const ALERT_EMAIL = "helping@easygiveqr.net";
const THROTTLE_MS = 60 * 60 * 1000; // 1 hour

// In-memory throttle cache (resets on server restart)
// In production, consider using Redis or database for persistence
const alertThrottle: Map<string, number> = new Map();

export type AlertType =
  | "webhook_failure"
  | "job_failure"
  | "checkout_failure"
  | "email_failure"
  | "database_error";

export interface AlertData {
  type: AlertType;
  message: string;
  details?: Record<string, any>; // No PII
  count?: number; // Number of failures (for repeated failures)
}

/**
 * Send a critical failure alert email (throttled)
 * 
 * @param alert - Alert data
 * @returns true if email was sent, false if throttled
 */
export async function sendAlertEmail(alert: AlertData): Promise<boolean> {
  const throttleKey = alert.type;
  const lastSent = alertThrottle.get(throttleKey);
  const now = Date.now();

  // Check throttle
  if (lastSent && now - lastSent < THROTTLE_MS) {
    console.warn(`[Alert] Throttled ${alert.type} alert (last sent ${Math.round((now - lastSent) / 1000)}s ago)`);
    return false;
  }

  // Generate email content
  const subject = `[EasyGiveQR Alert] ${getAlertSubject(alert.type)}`;
  const { html, text } = generateAlertEmail(alert);

  // Send email
  const result = await sendEmail({
    to: ALERT_EMAIL,
    subject,
    html,
    text,
  });

  if (result.success) {
    // Update throttle
    alertThrottle.set(throttleKey, now);
    console.log(`[Alert] Sent ${alert.type} alert email`);
    return true;
  } else {
    console.error(`[Alert] Failed to send ${alert.type} alert email:`, result.error);
    return false;
  }
}

function getAlertSubject(type: AlertType): string {
  switch (type) {
    case "webhook_failure":
      return "Stripe Webhook Failures";
    case "job_failure":
      return "Batch Job Failure";
    case "checkout_failure":
      return "Checkout Session Errors";
    case "email_failure":
      return "Email Delivery Failures";
    case "database_error":
      return "Database Error";
    default:
      return "System Alert";
  }
}

function generateAlertEmail(alert: AlertData): { html: string; text: string } {
  const timestamp = new Date().toISOString();
  const countText = alert.count && alert.count > 1 ? ` (${alert.count} occurrences)` : "";

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .alert-box { background: #fee; border-left: 4px solid #f00; padding: 16px; margin: 16px 0; }
    .details { background: #f5f5f5; padding: 12px; border-radius: 4px; margin: 12px 0; font-family: monospace; font-size: 12px; }
    .footer { margin-top: 24px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
  </style>
</head>
<body>
  <div class="container">
    <h1>EasyGiveQR Alert${countText}</h1>
    
    <div class="alert-box">
      <strong>Type:</strong> ${alert.type}<br>
      <strong>Time:</strong> ${timestamp}<br>
      <strong>Message:</strong> ${escapeHtml(alert.message)}
    </div>

    ${alert.details && Object.keys(alert.details).length > 0 ? `
    <div class="details">
      <strong>Details:</strong><br>
      <pre>${escapeHtml(JSON.stringify(alert.details, null, 2))}</pre>
    </div>
    ` : ""}

    <div class="footer">
      <p>This is an automated alert from EasyGiveQR.</p>
      <p>Alerts are throttled to at most once per hour per failure type.</p>
    </div>
  </div>
</body>
</html>
  `.trim();

  const text = `
EasyGiveQR Alert${countText}

Type: ${alert.type}
Time: ${timestamp}
Message: ${alert.message}

${alert.details && Object.keys(alert.details).length > 0 ? `
Details:
${JSON.stringify(alert.details, null, 2)}
` : ""}

---
This is an automated alert from EasyGiveQR.
Alerts are throttled to at most once per hour per failure type.
  `.trim();

  return { html, text };
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

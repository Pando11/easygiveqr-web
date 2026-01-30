/**
 * Centralized email sending via SendGrid
 * Enforces correct sender configuration
 */

export interface SendEmailOptions {
  to: string | string[];
  subject: string;
  html: string;
  text: string;
  replyTo?: string;
}

const MAX_RECIPIENTS_PER_MESSAGE = 5;

export interface SendEmailResult {
  success: boolean;
  error?: string;
}

/**
 * Send email via SendGrid
 * 
 * Enforces:
 * - From email = SENDGRID_FROM_EMAIL (required)
 * - Reply-to = SENDGRID_REPLY_TO_EMAIL (optional)
 * 
 * @throws Error if SENDGRID_FROM_EMAIL is missing
 */
export async function sendEmail(options: SendEmailOptions): Promise<SendEmailResult> {
  const apiKey = process.env.SENDGRID_API_KEY;
  const fromEmail = process.env.SENDGRID_FROM_EMAIL;
  const replyToEmail = process.env.SENDGRID_REPLY_TO_EMAIL;

  // Validate required configuration
  if (!apiKey) {
    return { success: false, error: "SENDGRID_API_KEY not configured" };
  }

  if (!fromEmail) {
    throw new Error(
      "SENDGRID_FROM_EMAIL must be set. " +
      "Set it to helping@easygiveqr.net in environment variables."
    );
  }

  // Normalize recipients to array
  const recipients = Array.isArray(options.to) ? options.to : [options.to];

  // Do not log full recipient lists (security)
  if (recipients.length === 0) {
    return { success: false, error: "No recipients specified" };
  }

  // If more than MAX_RECIPIENTS_PER_MESSAGE, chunk into multiple messages
  if (recipients.length > MAX_RECIPIENTS_PER_MESSAGE) {
    // Send in chunks
    const chunks: string[][] = [];
    for (let i = 0; i < recipients.length; i += MAX_RECIPIENTS_PER_MESSAGE) {
      chunks.push(recipients.slice(i, i + MAX_RECIPIENTS_PER_MESSAGE));
    }

    // Send each chunk
    const results = await Promise.all(
      chunks.map((chunk) =>
        sendEmail({
          ...options,
          to: chunk,
        })
      )
    );

    // Return success if all chunks succeeded
    const allSuccess = results.every((r) => r.success);
    if (allSuccess) {
      return { success: true };
    } else {
      const errors = results.filter((r) => !r.success).map((r) => r.error).join("; ");
      return { success: false, error: `Some emails failed: ${errors}` };
    }
  }

  try {
    const response = await fetch("https://api.sendgrid.com/v3/mail/send", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        personalizations: [
          {
            to: recipients.map((email) => ({ email })),
          },
        ],
        from: { email: fromEmail },
        reply_to: replyToEmail ? { email: replyToEmail } : undefined,
        subject: options.subject,
        content: [
          { type: "text/plain", value: options.text },
          { type: "text/html", value: options.html },
        ],
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      // Do not log full error response (may contain sensitive data)
      return {
        success: false,
        error: `SendGrid API error: ${response.status}`,
      };
    }

    return { success: true };
  } catch (err: any) {
    return {
      success: false,
      error: err?.message || "Failed to send email",
    };
  }
}

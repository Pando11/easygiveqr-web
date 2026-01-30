/**
 * Consolidated email templates
 * Exports functions for weekly summary, annual receipt, and engagement notification
 */

// Re-export existing template functions
export {
  generateEmail as weeklySummaryEN,
  generateEnglishEmail as weeklySummaryENRaw,
  generateSpanishEmail as weeklySummaryESRaw,
} from "../emailTemplates";

export {
  generateEnglishReceipt as annualReceiptEN,
  generateSpanishReceipt as annualReceiptES,
} from "../receiptTemplates";

export {
  generateEngagementEmailSubject,
  generateEngagementEmailHtml,
  generateEngagementEmailText,
} from "../engagementEmailTemplates";

// Re-export types for convenience
export type { EngagementEmailData } from "../engagementEmailTemplates";

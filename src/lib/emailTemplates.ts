/**
 * Email templates for weekly church summary emails
 * Supports English (EN) and Spanish (ES)
 */

interface WeeklySummaryData {
  churchDisplayName: string;
  weekStart: string; // Formatted date
  weekEnd: string; // Formatted date
  weeklyTotal: number; // in cents
  weeklyTotalFormatted: string; // formatted currency
  oneTimeTotal: number; // in cents
  oneTimeTotalFormatted: string;
  monthlyTotal: number; // in cents (currently 0, TODO)
  monthlyTotalFormatted: string;
  monthToDateTotal: number; // in cents
  monthToDateTotalFormatted: string;
  previousWeekTotal: number; // in cents
  previousWeekTotalFormatted: string;
  weekOverWeekChange: number; // percentage
  weekOverWeekChangeFormatted: string; // with + or - sign
  currency: string; // e.g., "usd"
}

/**
 * Format currency amount from cents
 */
function formatCurrency(cents: number, currency: string = "usd"): string {
  const amount = cents / 100;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(amount);
}

/**
 * Format percentage change
 */
function formatPercentageChange(change: number): string {
  const sign = change >= 0 ? "+" : "";
  return `${sign}${change.toFixed(1)}%`;
}

/**
 * English email template
 */
export function generateEnglishEmail(data: WeeklySummaryData): { subject: string; html: string; text: string } {
  const subject = `Weekly Giving Summary — ${data.churchDisplayName}`;

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
    .summary-box { background: #f9f9f9; padding: 15px; border-radius: 6px; margin: 15px 0; }
    .total { font-size: 24px; font-weight: bold; color: #1D4ED8; margin: 10px 0; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
    .change-positive { color: #059669; }
    .change-negative { color: #dc2626; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Weekly Giving Summary</h1>
      <p><strong>${data.churchDisplayName}</strong></p>
    </div>

    <p>Here is your weekly giving summary for the period:</p>
    <p><strong>${data.weekStart}</strong> to <strong>${data.weekEnd}</strong></p>

    <div class="summary-box">
      <h2>This Week's Total</h2>
      <div class="total">${data.weeklyTotalFormatted}</div>
      
      <p><strong>Breakdown:</strong></p>
      <ul>
        <li>One-time donations: ${data.oneTimeTotalFormatted}</li>
        <li>Monthly recurring: ${data.monthlyTotalFormatted}</li>
      </ul>
    </div>

    <div class="summary-box">
      <h2>Month-to-Date</h2>
      <div class="total">${data.monthToDateTotalFormatted}</div>
    </div>

    <div class="summary-box">
      <h2>Week-over-Week Comparison</h2>
      <p>Previous week: ${data.previousWeekTotalFormatted}</p>
      <p class="${data.weekOverWeekChange >= 0 ? "change-positive" : "change-negative"}">
        Change: ${data.weekOverWeekChangeFormatted}
      </p>
    </div>

    <div class="summary-box">
      <h2>Processing & Deposit</h2>
      <p><strong>Processing Fees:</strong> Fees are handled by Stripe. Detailed fee breakdown coming soon.</p>
      <p><strong>Deposit Status:</strong> Scheduled for Wednesday payout via Stripe</p>
    </div>

    <div class="footer">
      <p><strong>No action required.</strong> This is an automated summary.</p>
      <p>If you have questions, please contact your church administrator.</p>
    </div>
  </div>
</body>
</html>
  `.trim();

  const text = `
Weekly Giving Summary — ${data.churchDisplayName}

Period: ${data.weekStart} to ${data.weekEnd}

THIS WEEK'S TOTAL
${data.weeklyTotalFormatted}

Breakdown:
- One-time donations: ${data.oneTimeTotalFormatted}
- Monthly recurring: ${data.monthlyTotalFormatted}

MONTH-TO-DATE
${data.monthToDateTotalFormatted}

WEEK-OVER-WEEK COMPARISON
Previous week: ${data.previousWeekTotalFormatted}
Change: ${data.weekOverWeekChangeFormatted}

PROCESSING & DEPOSIT
Processing Fees: Fees are handled by Stripe. Detailed fee breakdown coming soon.
Deposit Status: Scheduled for Wednesday payout via Stripe

No action required. This is an automated summary.
  `.trim();

  return { subject, html, text };
}

/**
 * Spanish email template
 */
export function generateSpanishEmail(data: WeeklySummaryData): { subject: string; html: string; text: string } {
  const subject = `Resumen Semanal de Donaciones — ${data.churchDisplayName}`;

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
    .summary-box { background: #f9f9f9; padding: 15px; border-radius: 6px; margin: 15px 0; }
    .total { font-size: 24px; font-weight: bold; color: #1D4ED8; margin: 10px 0; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
    .change-positive { color: #059669; }
    .change-negative { color: #dc2626; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Resumen Semanal de Donaciones</h1>
      <p><strong>${data.churchDisplayName}</strong></p>
    </div>

    <p>Aquí está su resumen semanal de donaciones para el período:</p>
    <p><strong>${data.weekStart}</strong> a <strong>${data.weekEnd}</strong></p>

    <div class="summary-box">
      <h2>Total de Esta Semana</h2>
      <div class="total">${data.weeklyTotalFormatted}</div>
      
      <p><strong>Desglose:</strong></p>
      <ul>
        <li>Donaciones únicas: ${data.oneTimeTotalFormatted}</li>
        <li>Recurrencias mensuales: ${data.monthlyTotalFormatted}</li>
      </ul>
    </div>

    <div class="summary-box">
      <h2>Total del Mes</h2>
      <div class="total">${data.monthToDateTotalFormatted}</div>
    </div>

    <div class="summary-box">
      <h2>Comparación Semana a Semana</h2>
      <p>Semana anterior: ${data.previousWeekTotalFormatted}</p>
      <p class="${data.weekOverWeekChange >= 0 ? "change-positive" : "change-negative"}">
        Cambio: ${data.weekOverWeekChangeFormatted}
      </p>
    </div>

    <div class="summary-box">
      <h2>Procesamiento y Depósito</h2>
      <p><strong>Tarifas de Procesamiento:</strong> Las tarifas son manejadas por Stripe. Desglose detallado próximamente.</p>
      <p><strong>Estado del Depósito:</strong> Programado para pago del miércoles vía Stripe</p>
    </div>

    <div class="footer">
      <p><strong>No se requiere acción.</strong> Este es un resumen automatizado.</p>
      <p>Si tiene preguntas, por favor contacte al administrador de su iglesia.</p>
    </div>
  </div>
</body>
</html>
  `.trim();

  const text = `
Resumen Semanal de Donaciones — ${data.churchDisplayName}

Período: ${data.weekStart} a ${data.weekEnd}

TOTAL DE ESTA SEMANA
${data.weeklyTotalFormatted}

Desglose:
- Donaciones únicas: ${data.oneTimeTotalFormatted}
- Recurrencias mensuales: ${data.monthlyTotalFormatted}

TOTAL DEL MES
${data.monthToDateTotalFormatted}

COMPARACIÓN SEMANA A SEMANA
Semana anterior: ${data.previousWeekTotalFormatted}
Cambio: ${data.weekOverWeekChangeFormatted}

PROCESAMIENTO Y DEPÓSITO
Tarifas de Procesamiento: Las tarifas son manejadas por Stripe. Desglose detallado próximamente.
Estado del Depósito: Programado para pago del miércoles vía Stripe

No se requiere acción. Este es un resumen automatizado.
  `.trim();

  return { subject, html, text };
}

/**
 * Generate email based on preferred language
 */
export function generateEmail(
  data: WeeklySummaryData,
  preferredLanguage: "EN" | "ES" = "EN"
): { subject: string; html: string; text: string } {
  // Format all currency values
  const formattedData: WeeklySummaryData = {
    ...data,
    weeklyTotalFormatted: formatCurrency(data.weeklyTotal, data.currency),
    oneTimeTotalFormatted: formatCurrency(data.oneTimeTotal, data.currency),
    monthlyTotalFormatted: formatCurrency(data.monthlyTotal, data.currency),
    monthToDateTotalFormatted: formatCurrency(data.monthToDateTotal, data.currency),
    previousWeekTotalFormatted: formatCurrency(data.previousWeekTotal, data.currency),
    weekOverWeekChangeFormatted: formatPercentageChange(data.weekOverWeekChange),
  };

  if (preferredLanguage === "ES") {
    return generateSpanishEmail(formattedData);
  }
  return generateEnglishEmail(formattedData);
}

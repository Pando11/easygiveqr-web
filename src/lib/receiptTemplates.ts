/**
 * Email templates for annual tax receipts
 * Supports English (EN) and Spanish (ES)
 */

interface ReceiptData {
  churchDisplayName: string;
  churchLegalName: string;
  ein: string;
  year: number;
  totalAmount: number; // in cents
  totalAmountFormatted: string; // formatted currency
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
 * English receipt template
 */
export function generateEnglishReceipt(data: ReceiptData): { subject: string; html: string; text: string } {
  const subject = `${data.churchDisplayName} — ${data.year} Annual Donation Receipt`;

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center; }
    .receipt-box { background: #ffffff; border: 2px solid #ddd; padding: 20px; border-radius: 6px; margin: 20px 0; }
    .total { font-size: 28px; font-weight: bold; color: #1D4ED8; margin: 15px 0; text-align: center; }
    .info-row { margin: 10px 0; padding: 8px 0; border-bottom: 1px solid #eee; }
    .info-label { font-weight: bold; display: inline-block; width: 150px; }
    .irs-notice { background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; font-size: 13px; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Annual Donation Receipt</h1>
      <p><strong>${data.churchDisplayName}</strong></p>
      <p>Tax Year ${data.year}</p>
    </div>

    <div class="receipt-box">
      <h2 style="text-align: center; margin-top: 0;">Total Donations</h2>
      <div class="total">${data.totalAmountFormatted}</div>
      
      <div class="info-row">
        <span class="info-label">Organization:</span>
        <span>${data.churchLegalName}</span>
      </div>
      
      <div class="info-row">
        <span class="info-label">EIN:</span>
        <span>${data.ein}</span>
      </div>
      
      <div class="info-row">
        <span class="info-label">Tax Year:</span>
        <span>${data.year}</span>
      </div>
    </div>

    <div class="irs-notice">
      <p><strong>IRS Notice:</strong></p>
      <p>No goods or services were provided in exchange for this contribution, except to the extent of any intangible religious benefits provided. This receipt is provided for your tax records. You may deduct the full amount of your contribution on your federal income tax return if you itemize deductions, subject to applicable limitations.</p>
      <p>This organization is a tax-exempt organization under Section 501(c)(3) of the Internal Revenue Code. Contributions are tax-deductible to the extent allowed by law.</p>
    </div>

    <div class="footer">
      <p>This is an official tax receipt for your records.</p>
      <p>Please retain this receipt for your tax preparation.</p>
      <p>If you have questions, please contact ${data.churchDisplayName}.</p>
    </div>
  </div>
</body>
</html>
  `.trim();

  const text = `
ANNUAL DONATION RECEIPT
${data.churchDisplayName}
Tax Year ${data.year}

TOTAL DONATIONS
${data.totalAmountFormatted}

Organization: ${data.churchLegalName}
EIN: ${data.ein}
Tax Year: ${data.year}

IRS NOTICE:
No goods or services were provided in exchange for this contribution, except to the extent of any intangible religious benefits provided. This receipt is provided for your tax records. You may deduct the full amount of your contribution on your federal income tax return if you itemize deductions, subject to applicable limitations.

This organization is a tax-exempt organization under Section 501(c)(3) of the Internal Revenue Code. Contributions are tax-deductible to the extent allowed by law.

This is an official tax receipt for your records.
Please retain this receipt for your tax preparation.
If you have questions, please contact ${data.churchDisplayName}.
  `.trim();

  return { subject, html, text };
}

/**
 * Spanish receipt template
 */
export function generateSpanishReceipt(data: ReceiptData): { subject: string; html: string; text: string } {
  const subject = `${data.churchDisplayName} — Recibo de Donación Anual ${data.year}`;

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center; }
    .receipt-box { background: #ffffff; border: 2px solid #ddd; padding: 20px; border-radius: 6px; margin: 20px 0; }
    .total { font-size: 28px; font-weight: bold; color: #1D4ED8; margin: 15px 0; text-align: center; }
    .info-row { margin: 10px 0; padding: 8px 0; border-bottom: 1px solid #eee; }
    .info-label { font-weight: bold; display: inline-block; width: 150px; }
    .irs-notice { background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0; font-size: 13px; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Recibo de Donación Anual</h1>
      <p><strong>${data.churchDisplayName}</strong></p>
      <p>Año Fiscal ${data.year}</p>
    </div>

    <div class="receipt-box">
      <h2 style="text-align: center; margin-top: 0;">Total de Donaciones</h2>
      <div class="total">${data.totalAmountFormatted}</div>
      
      <div class="info-row">
        <span class="info-label">Organización:</span>
        <span>${data.churchLegalName}</span>
      </div>
      
      <div class="info-row">
        <span class="info-label">EIN:</span>
        <span>${data.ein}</span>
      </div>
      
      <div class="info-row">
        <span class="info-label">Año Fiscal:</span>
        <span>${data.year}</span>
      </div>
    </div>

    <div class="irs-notice">
      <p><strong>Aviso del IRS:</strong></p>
      <p>No se proporcionaron bienes o servicios a cambio de esta contribución, excepto en la medida de cualquier beneficio religioso intangible proporcionado. Este recibo se proporciona para sus registros fiscales. Puede deducir el monto total de su contribución en su declaración de impuestos sobre la renta federal si detalla las deducciones, sujeto a las limitaciones aplicables.</p>
      <p>Esta organización es una organización exenta de impuestos bajo la Sección 501(c)(3) del Código de Rentas Internas. Las contribuciones son deducibles de impuestos en la medida permitida por la ley.</p>
    </div>

    <div class="footer">
      <p>Este es un recibo fiscal oficial para sus registros.</p>
      <p>Por favor, conserve este recibo para su preparación de impuestos.</p>
      <p>Si tiene preguntas, por favor contacte a ${data.churchDisplayName}.</p>
    </div>
  </div>
</body>
</html>
  `.trim();

  const text = `
RECIBO DE DONACIÓN ANUAL
${data.churchDisplayName}
Año Fiscal ${data.year}

TOTAL DE DONACIONES
${data.totalAmountFormatted}

Organización: ${data.churchLegalName}
EIN: ${data.ein}
Año Fiscal: ${data.year}

AVISO DEL IRS:
No se proporcionaron bienes o servicios a cambio de esta contribución, excepto en la medida de cualquier beneficio religioso intangible proporcionado. Este recibo se proporciona para sus registros fiscales. Puede deducir el monto total de su contribución en su declaración de impuestos sobre la renta federal si detalla las deducciones, sujeto a las limitaciones aplicables.

Esta organización es una organización exenta de impuestos bajo la Sección 501(c)(3) del Código de Rentas Internas. Las contribuciones son deducibles de impuestos en la medida permitida por la ley.

Este es un recibo fiscal oficial para sus registros.
Por favor, conserve este recibo para su preparación de impuestos.
Si tiene preguntas, por favor contacte a ${data.churchDisplayName}.
  `.trim();

  return { subject, html, text };
}

/**
 * Generate receipt email based on preferred language
 */
export function generateReceipt(
  data: ReceiptData,
  preferredLanguage: "EN" | "ES" = "EN"
): { subject: string; html: string; text: string } {
  // Format currency
  const formattedData: ReceiptData = {
    ...data,
    totalAmountFormatted: formatCurrency(data.totalAmount, data.currency),
  };

  if (preferredLanguage === "ES") {
    return generateSpanishReceipt(formattedData);
  }
  return generateEnglishReceipt(formattedData);
}

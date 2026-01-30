/**
 * Email templates for church onboarding completion (EN/ES)
 */

export interface OnboardingEmailData {
  churchName: string;
  donateUrl: string;
  qrCodeUrl: string | null;
  logoUrl: string | null;
  prayerUrl: string;
  visitorUrl: string;
  volunteerUrl: string;
  stripeOnboardingUrl: string | null;
  stripeOnboardingStatus: string | null;
}

export function generateOnboardingEmailSubject(
  data: OnboardingEmailData,
  language: "EN" | "ES" = "EN"
): string {
  if (language === "ES") {
    return `EasyGiveQR Configuración — Próximos Pasos`;
  }
  return `EasyGiveQR Setup — Next Steps`;
}

export function generateOnboardingEmailHtml(
  data: OnboardingEmailData,
  language: "EN" | "ES" = "EN"
): string {
  const isES = language === "ES";

  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; text-align: center; }
    .section { margin: 20px 0; padding: 15px; background: #f9f9f9; border-radius: 6px; }
    .url-box { background: #fff; padding: 12px; border: 1px solid #ddd; border-radius: 4px; margin: 8px 0; word-break: break-all; font-family: monospace; font-size: 12px; }
    .button { display: inline-block; padding: 12px 24px; background: #1D4ED8; color: white; text-decoration: none; border-radius: 6px; margin: 8px 0; }
    .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>${isES ? "EasyGiveQR Configuración" : "EasyGiveQR Setup"}</h1>
      <p><strong>${data.churchName}</strong></p>
    </div>

    <p>${isES ? "¡Bienvenido a EasyGiveQR! Su iglesia ha sido configurada. Aquí está toda la información que necesita:" : "Welcome to EasyGiveQR! Your church has been set up. Here's all the information you need:"}</p>

    <div class="section">
      <h2>${isES ? "Enlace de Donación" : "Donation Link"}</h2>
      <div class="url-box">${data.donateUrl}</div>
      <p><a href="${data.donateUrl}" class="button">${isES ? "Probar Enlace de Donación" : "Test Donation Link"}</a></p>
    </div>

    ${data.qrCodeUrl ? `
    <div class="section">
      <h2>${isES ? "Código QR" : "QR Code"}</h2>
      <p>${isES ? "Su código QR está listo. Puede descargarlo desde:" : "Your QR code is ready. You can download it from:"}</p>
      <div class="url-box">${data.qrCodeUrl}</div>
      <p><img src="${data.qrCodeUrl}" alt="QR Code" style="max-width: 200px; margin: 16px 0;" /></p>
    </div>
    ` : ""}

    <div class="section">
      <h2>${isES ? "Formularios de Participación" : "Engagement Forms"}</h2>
      <p>${isES ? "Enlaces a los formularios de participación:" : "Links to engagement forms:"}</p>
      <ul>
        <li><strong>${isES ? "Solicitud de Oración" : "Prayer Request"}:</strong> <a href="${data.prayerUrl}">${data.prayerUrl}</a></li>
        <li><strong>${isES ? "Conectar Visitante" : "Visitor Connect"}:</strong> <a href="${data.visitorUrl}">${data.visitorUrl}</a></li>
        <li><strong>${isES ? "Interés en Voluntariado" : "Volunteer Interest"}:</strong> <a href="${data.volunteerUrl}">${data.volunteerUrl}</a></li>
      </ul>
    </div>

    ${data.stripeOnboardingUrl ? `
    <div class="section" style="background: #fff3cd; border-left: 4px solid #ffc107;">
      <h2>${isES ? "⚠️ Acción Requerida: Configuración de Pagos" : "⚠️ Action Required: Payment Setup"}</h2>
      <p>${isES ? "Para recibir donaciones, debe completar la configuración de Stripe Connect:" : "To receive donations, you must complete Stripe Connect setup:"}</p>
      <p><a href="${data.stripeOnboardingUrl}" class="button">${isES ? "Completar Configuración de Pagos" : "Complete Payment Setup"}</a></p>
      <p style="font-size: 12px; color: #666;">${isES ? "Este enlace expira en 24 horas. Si expira, puede solicitar un nuevo enlace." : "This link expires in 24 hours. If it expires, you can request a new link."}</p>
    </div>
    ` : data.stripeOnboardingStatus === "complete" ? `
    <div class="section" style="background: #d1fae5; border-left: 4px solid #10b981;">
      <h2>${isES ? "✓ Configuración de Pagos Completada" : "✓ Payment Setup Complete"}</h2>
      <p>${isES ? "Su cuenta de Stripe Connect está configurada y lista para recibir donaciones." : "Your Stripe Connect account is set up and ready to receive donations."}</p>
    </div>
    ` : ""}

    <div class="footer">
      <p><strong>${isES ? "No se requiere acción adicional" : "No additional action required"}</strong> ${isES ? "excepto completar la configuración de pagos si aún no lo ha hecho." : "except completing payment setup if you haven't already."}</p>
      <p>${isES ? "Si tiene preguntas, contáctenos en" : "If you have questions, contact us at"} <a href="mailto:helping@easygiveqr.net">helping@easygiveqr.net</a></p>
    </div>
  </div>
</body>
</html>
  `.trim();

  return html;
}

export function generateOnboardingEmailText(
  data: OnboardingEmailData,
  language: "EN" | "ES" = "EN"
): string {
  const isES = language === "ES";

  let text = `${isES ? "EasyGiveQR Configuración" : "EasyGiveQR Setup"}\n`;
  text += `${data.churchName}\n\n`;
  text += `${isES ? "¡Bienvenido a EasyGiveQR! Su iglesia ha sido configurada." : "Welcome to EasyGiveQR! Your church has been set up."}\n\n`;

  text += `${isES ? "ENLACE DE DONACIÓN" : "DONATION LINK"}\n`;
  text += `${data.donateUrl}\n\n`;

  if (data.qrCodeUrl) {
    text += `${isES ? "CÓDIGO QR" : "QR CODE"}\n`;
    text += `${data.qrCodeUrl}\n\n`;
  }

  text += `${isES ? "FORMULARIOS DE PARTICIPACIÓN" : "ENGAGEMENT FORMS"}\n`;
  text += `${isES ? "Solicitud de Oración" : "Prayer Request"}: ${data.prayerUrl}\n`;
  text += `${isES ? "Conectar Visitante" : "Visitor Connect"}: ${data.visitorUrl}\n`;
  text += `${isES ? "Interés en Voluntariado" : "Volunteer Interest"}: ${data.volunteerUrl}\n\n`;

  if (data.stripeOnboardingUrl) {
    text += `${isES ? "⚠️ ACCIÓN REQUERIDA: CONFIGURACIÓN DE PAGOS" : "⚠️ ACTION REQUIRED: PAYMENT SETUP"}\n`;
    text += `${isES ? "Para recibir donaciones, complete la configuración:" : "To receive donations, complete setup:"}\n`;
    text += `${data.stripeOnboardingUrl}\n\n`;
  } else if (data.stripeOnboardingStatus === "complete") {
    text += `${isES ? "✓ CONFIGURACIÓN DE PAGOS COMPLETADA" : "✓ PAYMENT SETUP COMPLETE"}\n\n`;
  }

  text += `---\n`;
  text += `${isES ? "No se requiere acción adicional" : "No additional action required"} ${isES ? "excepto completar la configuración de pagos si aún no lo ha hecho." : "except completing payment setup if you haven't already."}\n`;
  text += `${isES ? "Preguntas? helping@easygiveqr.net" : "Questions? helping@easygiveqr.net"}\n`;

  return text;
}

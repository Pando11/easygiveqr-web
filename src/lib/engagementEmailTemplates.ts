/**
 * Email templates for engagement submissions (EN/ES)
 */

import type { EngagementType } from "./engagementTranslations";

export interface EngagementEmailData {
  churchName: string;
  type: EngagementType;
  name?: string;
  email?: string;
  phone?: string;
  message?: string;
  meta?: Record<string, any>;
}

function getTypeLabel(type: EngagementType, language: "EN" | "ES"): string {
  if (language === "ES") {
    switch (type) {
      case "prayer":
        return "Solicitud de Oración";
      case "visitor":
        return "Conectar Visitante";
      case "volunteer":
        return "Interés en Voluntariado";
    }
  } else {
    switch (type) {
      case "prayer":
        return "Prayer Request";
      case "visitor":
        return "Visitor Connect";
      case "volunteer":
        return "Volunteer Interest";
    }
  }
}

export function generateEngagementEmailSubject(
  data: EngagementEmailData,
  language: "EN" | "ES" = "EN"
): string {
  const typeLabel = getTypeLabel(data.type, language);
  if (language === "ES") {
    return `Nueva ${typeLabel} — ${data.churchName}`;
  }
  return `New ${typeLabel} — ${data.churchName}`;
}

export function generateEngagementEmailHtml(
  data: EngagementEmailData,
  language: "EN" | "ES" = "EN"
): string {
  const typeLabel = getTypeLabel(data.type, language);
  
  const isES = language === "ES";
  
  const html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
    .container { max-width: 600px; margin: 0 auto; padding: 20px; }
    .header { background: #f5f5f5; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
    .field { margin-bottom: 15px; }
    .label { font-weight: bold; color: #555; }
    .value { margin-top: 5px; color: #333; }
    .meta { background: #f9f9f9; padding: 15px; border-radius: 4px; margin-top: 20px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2>${isES ? "Nueva" : "New"} ${typeLabel}</h2>
      <p><strong>${isES ? "Iglesia" : "Church"}:</strong> ${data.churchName}</p>
    </div>
    
    ${data.name ? `
    <div class="field">
      <div class="label">${isES ? "Nombre" : "Name"}:</div>
      <div class="value">${data.name}</div>
    </div>
    ` : ""}
    
    ${data.email ? `
    <div class="field">
      <div class="label">${isES ? "Correo Electrónico" : "Email"}:</div>
      <div class="value"><a href="mailto:${data.email}">${data.email}</a></div>
    </div>
    ` : ""}
    
    ${data.phone ? `
    <div class="field">
      <div class="label">${isES ? "Teléfono" : "Phone"}:</div>
      <div class="value">${data.phone}</div>
    </div>
    ` : ""}
    
    ${data.message ? `
    <div class="field">
      <div class="label">${isES ? "Mensaje" : "Message"}:</div>
      <div class="value">${data.message.replace(/\n/g, "<br>")}</div>
    </div>
    ` : ""}
    
    ${data.meta && Object.keys(data.meta).length > 0 ? `
    <div class="meta">
      <div class="label">${isES ? "Información Adicional" : "Additional Information"}:</div>
      <pre style="white-space: pre-wrap; font-family: Arial, sans-serif;">${JSON.stringify(data.meta, null, 2)}</pre>
    </div>
    ` : ""}
    
    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 12px;">
      <p>${isES ? "Este mensaje fue enviado desde el formulario de participación de la iglesia." : "This message was sent from the church engagement form."}</p>
    </div>
  </div>
</body>
</html>
  `.trim();
  
  return html;
}

export function generateEngagementEmailText(
  data: EngagementEmailData,
  language: "EN" | "ES" = "EN"
): string {
  const typeLabel = getTypeLabel(data.type, language);
  const isES = language === "ES";
  
  let text = `${isES ? "Nueva" : "New"} ${typeLabel}\n`;
  text += `${isES ? "Iglesia" : "Church"}: ${data.churchName}\n\n`;
  
  if (data.name) {
    text += `${isES ? "Nombre" : "Name"}: ${data.name}\n`;
  }
  if (data.email) {
    text += `${isES ? "Correo Electrónico" : "Email"}: ${data.email}\n`;
  }
  if (data.phone) {
    text += `${isES ? "Teléfono" : "Phone"}: ${data.phone}\n`;
  }
  if (data.message) {
    text += `\n${isES ? "Mensaje" : "Message"}:\n${data.message}\n`;
  }
  if (data.meta && Object.keys(data.meta).length > 0) {
    text += `\n${isES ? "Información Adicional" : "Additional Information"}:\n${JSON.stringify(data.meta, null, 2)}\n`;
  }
  
  text += `\n---\n${isES ? "Este mensaje fue enviado desde el formulario de participación de la iglesia." : "This message was sent from the church engagement form."}`;
  
  return text;
}

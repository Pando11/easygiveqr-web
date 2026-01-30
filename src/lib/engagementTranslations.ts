/**
 * Engagement forms translations (EN/ES)
 */

export type Language = "EN" | "ES";

export type EngagementType = "prayer" | "visitor" | "volunteer";

export interface EngagementTranslations {
  // Prayer Request
  prayerTitle: string;
  prayerSubtitle: string;
  prayerNameLabel: string;
  prayerEmailLabel: string;
  prayerPhoneLabel: string;
  prayerMessageLabel: string;
  prayerMessagePlaceholder: string;
  prayerSubmitButton: string;
  prayerSubmittedTitle: string;
  prayerSubmittedMessage: string;
  
  // Visitor Connect
  visitorTitle: string;
  visitorSubtitle: string;
  visitorNameLabel: string;
  visitorNameRequired: string;
  visitorEmailLabel: string;
  visitorPhoneLabel: string;
  visitorMessageLabel: string;
  visitorMessagePlaceholder: string;
  visitorSubmitButton: string;
  visitorSubmittedTitle: string;
  visitorSubmittedMessage: string;
  
  // Volunteer Interest
  volunteerTitle: string;
  volunteerSubtitle: string;
  volunteerNameLabel: string;
  volunteerNameRequired: string;
  volunteerEmailLabel: string;
  volunteerPhoneLabel: string;
  volunteerMessageLabel: string;
  volunteerMessagePlaceholder: string;
  volunteerSubmitButton: string;
  volunteerSubmittedTitle: string;
  volunteerSubmittedMessage: string;
  
  // Common
  optional: string;
  required: string;
  backToChurch: string;
  submitting: string;
  errorGeneric: string;
  errorMissingFields: string;
}

const translations: Record<Language, EngagementTranslations> = {
  EN: {
    prayerTitle: "Prayer Request",
    prayerSubtitle: "Share your prayer request with us. We'd love to pray for you.",
    prayerNameLabel: "Your Name",
    prayerEmailLabel: "Email",
    prayerPhoneLabel: "Phone",
    prayerMessageLabel: "Prayer Request",
    prayerMessagePlaceholder: "Please share your prayer request...",
    prayerSubmitButton: "Submit Prayer Request",
    prayerSubmittedTitle: "Prayer Request Submitted",
    prayerSubmittedMessage: "Thank you for sharing your prayer request. We will be praying for you.",
    
    visitorTitle: "Visitor Connect",
    visitorSubtitle: "Welcome! We'd love to connect with you.",
    visitorNameLabel: "Your Name",
    visitorNameRequired: "Name is required",
    visitorEmailLabel: "Email",
    visitorPhoneLabel: "Phone",
    visitorMessageLabel: "Message (Optional)",
    visitorMessagePlaceholder: "Tell us about yourself or how we can help...",
    visitorSubmitButton: "Submit",
    visitorSubmittedTitle: "Thank You!",
    visitorSubmittedMessage: "We've received your information and will be in touch soon.",
    
    volunteerTitle: "Volunteer Interest",
    volunteerSubtitle: "We'd love to have you serve with us. Let us know how you'd like to help.",
    volunteerNameLabel: "Your Name",
    volunteerNameRequired: "Name is required",
    volunteerEmailLabel: "Email",
    volunteerPhoneLabel: "Phone",
    volunteerMessageLabel: "How would you like to help?",
    volunteerMessagePlaceholder: "Share your interests, skills, or availability...",
    volunteerSubmitButton: "Submit Volunteer Interest",
    volunteerSubmittedTitle: "Thank You!",
    volunteerSubmittedMessage: "We've received your volunteer interest and will be in touch soon.",
    
    optional: "(Optional)",
    required: "(Required)",
    backToChurch: "Back to Church",
    submitting: "Submitting...",
    errorGeneric: "An error occurred. Please try again.",
    errorMissingFields: "Please fill in all required fields.",
  },
  ES: {
    prayerTitle: "Solicitud de Oración",
    prayerSubtitle: "Comparte tu solicitud de oración con nosotros. Nos encantaría orar por ti.",
    prayerNameLabel: "Tu Nombre",
    prayerEmailLabel: "Correo Electrónico",
    prayerPhoneLabel: "Teléfono",
    prayerMessageLabel: "Solicitud de Oración",
    prayerMessagePlaceholder: "Por favor comparte tu solicitud de oración...",
    prayerSubmitButton: "Enviar Solicitud de Oración",
    prayerSubmittedTitle: "Solicitud de Oración Enviada",
    prayerSubmittedMessage: "Gracias por compartir tu solicitud de oración. Estaremos orando por ti.",
    
    visitorTitle: "Conectar Visitante",
    visitorSubtitle: "¡Bienvenido! Nos encantaría conectarnos contigo.",
    visitorNameLabel: "Tu Nombre",
    visitorNameRequired: "El nombre es requerido",
    visitorEmailLabel: "Correo Electrónico",
    visitorPhoneLabel: "Teléfono",
    visitorMessageLabel: "Mensaje (Opcional)",
    visitorMessagePlaceholder: "Cuéntanos sobre ti o cómo podemos ayudar...",
    visitorSubmitButton: "Enviar",
    visitorSubmittedTitle: "¡Gracias!",
    visitorSubmittedMessage: "Hemos recibido tu información y nos pondremos en contacto pronto.",
    
    volunteerTitle: "Interés en Voluntariado",
    volunteerSubtitle: "Nos encantaría que sirvas con nosotros. Dinos cómo te gustaría ayudar.",
    volunteerNameLabel: "Tu Nombre",
    volunteerNameRequired: "El nombre es requerido",
    volunteerEmailLabel: "Correo Electrónico",
    volunteerPhoneLabel: "Teléfono",
    volunteerMessageLabel: "¿Cómo te gustaría ayudar?",
    volunteerMessagePlaceholder: "Comparte tus intereses, habilidades o disponibilidad...",
    volunteerSubmitButton: "Enviar Interés en Voluntariado",
    volunteerSubmittedTitle: "¡Gracias!",
    volunteerSubmittedMessage: "Hemos recibido tu interés en voluntariado y nos pondremos en contacto pronto.",
    
    optional: "(Opcional)",
    required: "(Requerido)",
    backToChurch: "Volver a la Iglesia",
    submitting: "Enviando...",
    errorGeneric: "Ocurrió un error. Por favor intenta de nuevo.",
    errorMissingFields: "Por favor completa todos los campos requeridos.",
  },
};

export function getEngagementTranslations(language: Language = "EN"): EngagementTranslations {
  return translations[language] || translations.EN;
}

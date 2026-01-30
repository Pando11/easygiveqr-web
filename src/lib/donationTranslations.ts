/**
 * Donation page translations (EN/ES)
 */

export type Language = "EN" | "ES";

export interface DonationTranslations {
  // Page title
  pageTitle: string;
  
  // Amount selection
  selectAmount: string;
  
  // Frequency
  frequency: string;
  oneTime: string;
  monthly: string;
  
  // Button
  donateButton: string;
  
  // Errors
  churchNotFound: string;
  donationsUnavailable: string;
  donationsUnavailableMessage: string;
  
  // Success page
  verifying: string;
  paymentReceived: string;
  waitingForConfirmation: string;
  retrying: string;
  retryButton: string;
  donationVerified: string;
  amount: string;
  currency: string;
  status: string;
  processed: string;
  backToDonate: string;
  
  // Cancel page
  donationCanceled: string;
  noPaymentCompleted: string;
  backToDonateCancel: string;
  
  // Loading
  loading: string;
}

const translations: Record<Language, DonationTranslations> = {
  EN: {
    pageTitle: "Donate",
    selectAmount: "Select Amount",
    frequency: "Frequency",
    oneTime: "One-time",
    monthly: "Monthly",
    donateButton: "Donate",
    churchNotFound: "Church Not Found",
    donationsUnavailable: "Donations Temporarily Unavailable",
    donationsUnavailableMessage:
      "Donations are not available at this time. Please try again later or contact the church directly.",
    verifying: "Verifying donation...",
    paymentReceived: "Payment received. Waiting for confirmation…",
    waitingForConfirmation: "Waiting for confirmation…",
    retrying: "Retrying...",
    retryButton: "Retry",
    donationVerified: "✓ Donation verified",
    amount: "Amount",
    currency: "Currency",
    status: "Status",
    processed: "Processed",
    backToDonate: "Back to donate",
    donationCanceled: "Donation Canceled",
    noPaymentCompleted: "No payment was completed.",
    backToDonateCancel: "Back to donate",
    loading: "Loading...",
  },
  ES: {
    pageTitle: "Donar",
    selectAmount: "Seleccionar Cantidad",
    frequency: "Frecuencia",
    oneTime: "Una vez",
    monthly: "Mensual",
    donateButton: "Donar",
    churchNotFound: "Iglesia no encontrada",
    donationsUnavailable: "Donaciones temporalmente no disponibles",
    donationsUnavailableMessage:
      "Las donaciones no están disponibles en este momento. Por favor, intente más tarde o póngase en contacto con la iglesia directamente.",
    verifying: "Verificando donación...",
    paymentReceived: "Pago recibido. Esperando confirmación…",
    waitingForConfirmation: "Esperando confirmación…",
    retrying: "Reintentando...",
    retryButton: "Reintentar",
    donationVerified: "✓ Donación verificada",
    amount: "Cantidad",
    currency: "Moneda",
    status: "Estado",
    processed: "Procesado",
    backToDonate: "Volver a donar",
    donationCanceled: "Donación Cancelada",
    noPaymentCompleted: "No se completó ningún pago.",
    backToDonateCancel: "Volver a donar",
    loading: "Cargando...",
  },
};

export function getDonationTranslations(language: Language = "EN"): DonationTranslations {
  return translations[language] || translations.EN;
}

/**
 * Donation availability messages in English and Spanish
 */

export function getDonationUnavailableMessage(
  language: "EN" | "ES" = "EN",
  reason?: string
): { title: string; message: string } {
  if (language === "ES") {
    return {
      title: "Donaciones temporalmente no disponibles",
      message:
        "Las donaciones no están disponibles en este momento. Por favor, intente más tarde o póngase en contacto con la iglesia directamente.",
    };
  }

  // English (default)
  return {
    title: "Donations Temporarily Unavailable",
    message:
      "Donations are not available at this time. Please try again later or contact the church directly.",
  };
}

export function getChurchNotFoundMessage(language: "EN" | "ES" = "EN"): { title: string; message: string } {
  if (language === "ES") {
    return {
      title: "Iglesia no encontrada",
      message: "No se pudo encontrar la iglesia solicitada. Por favor, verifique el enlace e intente nuevamente.",
    };
  }

  // English (default)
  return {
    title: "Church Not Found",
    message: "The requested church could not be found. Please check the link and try again.",
  };
}

export function getDonationsPausedMessage(language: "EN" | "ES" = "EN"): { title: string; message: string } {
  if (language === "ES") {
    return {
      title: "Donaciones Temporalmente Pausadas",
      message:
        "Las donaciones están temporalmente pausadas. Por favor, intente más tarde o póngase en contacto con la iglesia directamente.",
    };
  }

  // English (default)
  return {
    title: "Donations Temporarily Paused",
    message:
      "Donations are temporarily paused. Please try again later or contact the church directly.",
  };
}

export function getDonationTimeoutMessage(language: "EN" | "ES" = "EN"): { title: string; message: string } {
  if (language === "ES") {
    return {
      title: "Pago Recibido",
      message:
        "Hemos recibido su pago. Si necesita ayuda, por favor póngase en contacto con la iglesia directamente.",
    };
  }

  // English (default)
  return {
    title: "Payment Received",
    message: "We received your payment. If you need help, please contact the church directly.",
  };
}

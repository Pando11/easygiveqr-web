function showLoading(message = "Loading...") {
    hideLoading();

    const overlay = document.createElement("div");
    overlay.id = "globalLoading";
    overlay.style.cssText = [
        "position: fixed",
        "inset: 0",
        "background: rgba(15, 23, 42, 0.7)",
        "display: flex",
        "align-items: center",
        "justify-content: center",
        "z-index: 10000",
        "padding: 20px",
    ].join(";");

    overlay.innerHTML = `
        <div style="
            background: #fff;
            border-radius: 12px;
            padding: 22px 24px;
            width: min(92vw, 360px);
            text-align: center;
            box-shadow: 0 18px 34px rgba(0, 0, 0, 0.25);
        ">
            <div class="maverick-js-spinner" style="margin: 0 auto 14px;"></div>
            <p style="margin: 0; font-weight: 600; color: #1f2937;">${message}</p>
        </div>
    `;
    document.body.appendChild(overlay);
}

function hideLoading() {
    const overlay = document.getElementById("globalLoading");
    if (overlay) {
        overlay.remove();
    }
}

function showToast(message, kind = "success", timeout = 3000) {
    const toast = document.createElement("div");
    const isError = kind === "error";
    toast.style.cssText = [
        "position: fixed",
        "top: 16px",
        "right: 16px",
        `background: ${isError ? "#fee2e2" : "#d1fae5"}`,
        `color: ${isError ? "#991b1b" : "#065f46"}`,
        "padding: 14px 16px",
        "border-radius: 10px",
        `border-left: 4px solid ${isError ? "#ef4444" : "#10b981"}`,
        "max-width: min(92vw, 420px)",
        "box-shadow: 0 10px 22px rgba(15, 23, 42, 0.22)",
        "z-index: 10001",
        "font-weight: 600",
        "opacity: 0",
        "transform: translateY(-6px)",
        "transition: opacity 0.2s ease, transform 0.2s ease",
    ].join(";");
    toast.textContent = message;
    document.body.appendChild(toast);

    requestAnimationFrame(() => {
        toast.style.opacity = "1";
        toast.style.transform = "translateY(0)";
    });

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(-6px)";
        setTimeout(() => toast.remove(), 220);
    }, timeout);
}

function showSuccess(message) {
    showToast(message, "success", 3000);
}

function showError(message) {
    showToast(message, "error", 5000);
}

if (!document.getElementById("maverick-js-spinner-style")) {
    const style = document.createElement("style");
    style.id = "maverick-js-spinner-style";
    style.textContent = `
        .maverick-js-spinner {
            width: 42px;
            height: 42px;
            border-radius: 999px;
            border: 4px solid #e5e7eb;
            border-top-color: #10b981;
            animation: maverickJsSpin 1s linear infinite;
        }

        @keyframes maverickJsSpin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    `;
    document.head.appendChild(style);
}

window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.showSuccess = showSuccess;
window.showError = showError;

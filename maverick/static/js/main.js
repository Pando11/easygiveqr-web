function showLoading(message = "Loading...") {
    const existing = document.getElementById("globalLoading");
    if (existing) {
        existing.remove();
    }

    const loading = document.createElement("div");
    loading.id = "globalLoading";
    loading.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 9999;
    `;

    loading.innerHTML = `
        <div style="background: white; padding: 30px; border-radius: 12px; text-align: center;">
            <div style="border: 4px solid #f3f4f6; border-top: 4px solid #10b981; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite; margin: 0 auto 20px;"></div>
            <p style="margin: 0; color: #374151; font-weight: 600;">${message}</p>
        </div>
    `;

    document.body.appendChild(loading);
}

function hideLoading() {
    const loading = document.getElementById("globalLoading");
    if (loading) {
        loading.remove();
    }
}

function showError(message) {
    const error = document.createElement("div");
    error.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #fee2e2;
        color: #991b1b;
        padding: 15px 20px;
        border-radius: 8px;
        border-left: 4px solid #ef4444;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 10000;
        max-width: 400px;
    `;
    error.textContent = message;

    document.body.appendChild(error);
    setTimeout(() => {
        error.style.opacity = "0";
        error.style.transition = "opacity 0.3s";
        setTimeout(() => error.remove(), 300);
    }, 5000);
}

function showSuccess(message) {
    const success = document.createElement("div");
    success.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #d1fae5;
        color: #065f46;
        padding: 15px 20px;
        border-radius: 8px;
        border-left: 4px solid #10b981;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 10000;
        max-width: 400px;
    `;
    success.textContent = message;

    document.body.appendChild(success);
    setTimeout(() => {
        success.style.opacity = "0";
        success.style.transition = "opacity 0.3s";
        setTimeout(() => success.remove(), 300);
    }, 3000);
}

window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.showError = showError;
window.showSuccess = showSuccess;

const style = document.createElement("style");
style.textContent = `
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
document.head.appendChild(style);


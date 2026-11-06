"use strict";
(async () => {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.getAll("token").length === 1 ? params.get("token") : null;
  const requested = params.getAll("next").length === 1 ? params.get("next") : "";
  const next = /^(?:review|batch|assignment|report|material):[a-f0-9]{32}$/.test(requested) ? requested : "";
  history.replaceState(null, "", location.pathname);
  const status = document.getElementById("loginStatus");
  const button = document.getElementById("confirmLogin");
  async function post(path, body) {
    const response = await fetch(path, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось войти. Запросите новую ссылку в боте.");
    return data;
  }
  try {
    if (!token) throw new Error("Откройте свежую ссылку из бота. Для её получения отправьте /start.");
    const identity = await post("/api/v2/auth/bot/preview", { token });
    status.textContent = "Ваш профиль MAX: " + (identity.first_name || "Учитель");
    document.getElementById("loginConfirmHint").hidden = false;
    button.hidden = false;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await post("/api/v2/auth/bot", { token, confirm: true });
        location.replace(next ? "/?open=" + encodeURIComponent(next) : "/");
      } catch (error) {
        status.textContent = error.message;
        button.disabled = false;
      }
    });
  } catch (error) {
    status.textContent = error.message;
  }
  try {
    const response = await fetch("/api/v2/auth/me", { credentials: "same-origin" });
    const data = await response.json();
    if (data.max_url && /^https:\/\/max\.ru\/[A-Za-z0-9_]+(?:\?startapp)?$/.test(data.max_url)) {
      const link = document.getElementById("newBotLink");
      link.href = data.max_url;
      link.hidden = false;
    }
  } catch (_) { /* The original login error remains visible. */ }
})();

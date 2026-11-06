"use strict";
// Prepare private tickets before the click: MAX requires a direct user gesture.
const exportTickets = new Map();

function nativeDownloadAvailable() {
  return state.auth?.user?.kind === "max" && !!window.WebApp?.downloadFile;
}

function prepareExportTicket(artifactId) {
  const cacheKey = state.auth.csrf_token + ":" + artifactId;
  const cached = exportTickets.get(cacheKey);
  if (cached && (!cached.links || cached.links.expires_at * 1000 > Date.now() + 15000))
    return cached;
  const entry = { links: null, promise: null };
  entry.promise = request("/api/v2/exports/" + artifactId, { method: "POST" })
    .then((links) => {
      entry.links = links;
      return links;
    })
    .catch((error) => {
      if (exportTickets.get(cacheKey) === entry) exportTickets.delete(cacheKey);
      throw error;
    });
  // Keep only a bounded, session-specific in-memory cache, never localStorage.
  if (exportTickets.size >= 100) exportTickets.delete(exportTickets.keys().next().value);
  exportTickets.set(cacheKey, entry);
  return entry;
}

function bindArtifactDownload(anchor, artifactId, key, filename) {
  anchor.onclick = null;
  if (!nativeDownloadAvailable() || !artifactId) return;
  prepareExportTicket(artifactId).promise.catch(() => {});
  anchor.onclick = (event) => {
    if (!nativeDownloadAvailable()) return;
    event.preventDefault();
    const ticket = prepareExportTicket(artifactId);
    if (!ticket.links) {
      busy("Готовим файл", async () => {
        await ticket.promise;
        notice("Файл готов. Нажмите кнопку скачивания ещё раз.");
      });
      return;
    }
    if (!ticket.links[key]) {
      notice("Этот файл недоступен. Откройте комплект заново.", true);
      return;
    }
    try {
      // Do not put this call after await or in a Promise callback.
      const download = window.WebApp.downloadFile(
        new URL(ticket.links[key], location.origin).href, filename,
      );
      Promise.resolve(download)
        .then((result) => {
          if (result?.status === "cancelled") notice("Скачивание отменено.");
        })
        .catch(() => notice("MAX не смог скачать файл. Повторите скачивание.", true));
    } catch {
      notice("MAX не смог скачать файл. Повторите скачивание.", true);
    }
  };
}

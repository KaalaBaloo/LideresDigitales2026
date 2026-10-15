const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

async function req(path, opts = {}) {
  const r = await fetch(BASE + path, opts);
  const text = await r.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!r.ok) throw new Error((body && body.detail) || `HTTP ${r.status}`);
  return body;
}

const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });

export const api = {
  health: () => req("/health"),
  shops: () => req("/shops"),
  shop: (id) => req(`/shops/${id}`),
  patchShop: (id, body) => req(`/shops/${id}`, json("PATCH", body)),
  opportunities: (id, date) => req(`/shops/${id}/opportunities${date ? `?date=${date}` : ""}`),
  campaigns: (id) => req(`/shops/${id}/campaigns`),
  launch: (id, offer_type, duration_h = 3) => req(`/shops/${id}/campaigns`, json("POST", { offer_type, duration_h })),
  closeCampaign: (cid) => req(`/campaigns/${cid}/result`, json("POST", {})),
  recommendation: (id, slot, date) => req(`/shops/${id}/recommendation?slot=${slot}${date ? `&date=${date}` : ""}`),
  notifications: (id) => req(`/shops/${id}/notifications`),
  parkings: (lat, lon) => req(`/madrid/parkings/live?lat=${lat}&lon=${lon}&radius=800`),
  events: (lat, lon, from, to) => req(`/madrid/events?from=${from}&to=${to}&lat=${lat}&lon=${lon}&radius=800&limit=20`),
  sensorEval: (id) => req(`/sensor/eval?shop_id=${id}`),
  debugFrame: (file, shopId) => {
    const fd = new FormData();
    fd.append("image", file);
    fd.append("shop_id", String(shopId));
    return req("/sensor/debug-frame", { method: "POST", body: fd });
  },
};

export const SEGMENTS = {
  solo: { label: "Personas solas", short: "Solo", color: "#8a8f98" },
  dos_adultos: { label: "Parejas", short: "Parejas", color: "#4e79a7" },
  adulto_con_ninos: { label: "Adultos con niños", short: "Con niños", color: "#f28e2b" },
  familia_numerosa: { label: "Familias numerosas", short: "Fam. num.", color: "#e15759" },
  grupo_adultos_3_6: { label: "Grupos de 3–6 adultos", short: "Grupos 3–6", color: "#59a14f" },
  grupo_grande: { label: "Grupos grandes", short: "Grandes", color: "#b07aa1" },
};

export const eur = (v) => `${Math.round(v ?? 0).toLocaleString("es-ES")} €`;
export const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${Math.round(v * 100)} %`);
export const fmtDate = (d) => new Date(d).toLocaleDateString("es-ES", { weekday: "short", day: "numeric", month: "short" });
export const today = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Madrid" });

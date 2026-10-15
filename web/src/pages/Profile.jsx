import { useEffect, useState } from "react";
import { api, SEGMENTS } from "../api.js";
import { useShop } from "../App.jsx";

export default function Profile() {
  const { shop, reloadShop } = useShop();
  const [form, setForm] = useState(null);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setForm({
      capacity: shop.capacity ?? "",
      vetoed: new Set(shop.vetoed_offers || []),
      profile: { ...(shop.profile || {}) },
    });
  }, [shop]);
  if (!form) return null;

  const setP = (k, v) => setForm((f) => ({ ...f, profile: { ...f.profile, [k]: v } }));
  const toggle = (id) =>
    setForm((f) => {
      const v = new Set(f.vetoed);
      v.has(id) ? v.delete(id) : v.add(id);
      return { ...f, vetoed: v };
    });

  const save = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      await api.patchShop(shop.id, {
        capacity: form.capacity === "" ? null : Number(form.capacity),
        vetoed_offers: [...form.vetoed],
        profile: { ...form.profile, max_discount_pct: Number(form.profile.max_discount_pct) || 0 },
      });
      await reloadShop();
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e2) {
      setErr(e2.message);
    }
  };

  const p = form.profile;
  return (
    <section>
      <h1>Tu comercio</h1>
      <p className="muted">Un perfil mejor, recomendaciones más útiles.</p>
      <div className="card">
        <b>{shop.name}</b> · {shop.street}
        <div className="muted small">
          Local real del Censo de locales (id {shop.census_id_local}) · {p.census_epigrafe} · estación de aforo {shop.station_id}
          {shop.competitors_100m != null && ` · ${shop.competitors_100m} locales de la misma actividad a < 100 m`}
        </div>
      </div>
      <form className="card form" onSubmit={save}>
        <h2>Datos de tu tienda</h2>
        <label>Tipo de comercio<input value={p.business_type || ""} onChange={(e) => setP("business_type", e.target.value)} /></label>
        <label>Horario de apertura<input value={p.opening_hours || ""} onChange={(e) => setP("opening_hours", e.target.value)} /></label>
        <label>Franja preferida para campañas<input value={p.preferred_slot || ""} onChange={(e) => setP("preferred_slot", e.target.value)} /></label>
        <label>Aforo (personas)<input type="number" min="0" value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} /></label>
        <h2>A quién quieres atraer</h2>
        <label>Público principal<input value={p.target_audience || ""} onChange={(e) => setP("target_audience", e.target.value)} /></label>
        <label>También te interesan<input value={p.also_interested || ""} onChange={(e) => setP("also_interested", e.target.value)} /></label>
        {shop.audience && (
          <div className="small">
            Público observado por el sensor:{" "}
            {Object.entries(shop.audience)
              .map(([k, v]) => `${SEGMENTS[k]?.short || k} ${Math.round(v * 100)} %`)
              .join(" · ")}
          </div>
        )}
        <h2>Preferencias de campaña</h2>
        <label>Descuento máximo (%)<input type="number" min="0" max="100" value={p.max_discount_pct ?? ""} onChange={(e) => setP("max_discount_pct", e.target.value)} /></label>
        <label>Productos elegibles<input value={p.eligible_products || ""} onChange={(e) => setP("eligible_products", e.target.value)} /></label>
        <label>Canal<input value={p.channel || ""} onChange={(e) => setP("channel", e.target.value)} /></label>
        <label>Duración máxima (h)<input type="number" min="1" max="12" value={p.max_duration_h ?? 3} onChange={(e) => setP("max_duration_h", Number(e.target.value))} /></label>
        <fieldset>
          <legend>Ofertas que no quieres usar (vetadas)</legend>
          {(shop.offers_catalog || []).map((o) => (
            <label key={o.id} className="check">
              <input type="checkbox" checked={form.vetoed.has(o.id)} onChange={() => toggle(o.id)} />
              {o.titulo} <span className="muted small">({o.descuento_pct} %{o.requiere_grupo_par ? ", exige grupo par" : ""})</span>
            </label>
          ))}
        </fieldset>
        {err && <p className="error">{err}</p>}
        <button className="primary">{saved ? "Guardado ✓" : "Guardar perfil"}</button>
      </form>
      <p className="muted small">
        Tu perfil orienta el aprendizaje: el recomendador descarta las ofertas vetadas o por encima de tu descuento máximo.
      </p>
    </section>
  );
}

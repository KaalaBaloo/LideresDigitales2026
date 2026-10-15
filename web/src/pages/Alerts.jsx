import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, eur } from "../api.js";
import { useShop } from "../App.jsx";

export default function Alerts() {
  const { shop } = useShop();
  const [items, setItems] = useState(null);
  const [launched, setLaunched] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const load = () => api.notifications(shop.id).then(setItems).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 15000); // la demo envía fotogramas en directo
    return () => clearInterval(t);
  }, [shop.id]);

  const launch = async (offer) => {
    setBusy(true);
    setErr(null);
    try {
      setLaunched(await api.launch(shop.id, offer, shop.profile?.max_duration_h || 3));
      load();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const latest = items?.[0];
  const p = latest?.payload;
  return (
    <section>
      <h1>Una oferta para todos</h1>
      <p className="muted">Alertas y acción</p>
      {err && <p className="error">{err}</p>}
      {!items && <p className="muted">Cargando…</p>}
      {items && !latest && (
        <p className="card note">
          Aún no hay alertas. Se generan cuando el sensor envía agregados (ejecuta <code>scripts/send_frames.py</code>).
        </p>
      )}
      {latest && (
        <div className="card alert">
          <div className="muted small">
            {latest.day} · {latest.hour}:00 · redactado por {latest.text_source === "claude" ? "Claude (solo con datos agregados)" : "plantilla"}
          </div>
          <p className="big">{latest.text}</p>
          {p?.diagnosis?.length > 0 && (
            <>
              <h3>Por qué</h3>
              <ul className="list">
                {p.diagnosis.map((d) => (
                  <li key={d.code}>
                    {d.text} <span className="badge">confianza {Math.round(d.confidence * 100)} %</span>
                  </li>
                ))}
              </ul>
              <p className="muted small">Hipótesis basada en el patrón observado. Otros factores también pueden influir.</p>
            </>
          )}
          {p?.recommendation?.offer && (
            <div className="offer">
              <span className="badge">Recomendada</span>
              <h2>{p.recommendation.title}</h2>
              {p.opportunity && (
                <p className="small">
                  {p.opportunity.groups_seen} grupos vistos · {p.opportunity.groups_entering} entraron · pérdida estimada {eur(p.opportunity.loss_eur)}
                </p>
              )}
              {latest.status === "acted" || launched ? (
                <p className="ok">
                  Oferta lanzada{launched ? ` (${launched.starts_at.slice(11, 16)}–${launched.ends_at.slice(11, 16)})` : ""}. Verás el resultado en{" "}
                  <Link to="/aprendizajes">Aprendizajes</Link>.
                </p>
              ) : (
                <button className="primary" disabled={busy} onClick={() => launch(p.recommendation.offer)}>
                  {busy ? "Lanzando…" : "Lanzar oferta"}
                </button>
              )}
            </div>
          )}
          {p?.recommendation?.excluded?.length > 0 && (
            <p className="muted small">
              Descartadas: {p.recommendation.excluded.map((e) => `${e.offer} (${e.reason})`).join(" · ")}
            </p>
          )}
        </div>
      )}
      {items && items.length > 1 && (
        <div className="card">
          <h2>Anteriores</h2>
          <ul className="list small">
            {items.slice(1).map((n) => (
              <li key={n.id}>
                <b>
                  {n.day} {n.hour}:00
                </b>{" "}
                {n.text}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

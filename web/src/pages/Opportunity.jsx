import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, eur, SEGMENTS } from "../api.js";
import { useShop } from "../App.jsx";

export default function Opportunity() {
  const { shop } = useShop();
  const { date, hour } = useParams();
  const h = Number(hour);
  const [data, setData] = useState(null);
  const [rec, setRec] = useState(null);
  const [parkings, setParkings] = useState(null);
  const [events, setEvents] = useState(null);

  useEffect(() => {
    api.opportunities(shop.id, date).then(setData);
    api.recommendation(shop.id, h, date).then(setRec).catch(() => setRec(null));
    api.parkings(shop.lat, shop.lon).then(setParkings).catch(() => setParkings({ items: [] }));
    api.events(shop.lat, shop.lon, date, date).then(setEvents).catch(() => setEvents({ items: [] }));
  }, [shop.id, date, h]);

  const slot = data?.hours.find((x) => x.hour === h);
  const curve = data?.station.curve.find((c) => c.hour === h);
  const segs = Object.values(slot?.segments || {}).sort((a, b) => b.loss_eur - a.loss_eur);

  return (
    <section>
      <Link to="/" className="back">← Tu calle, hoy</Link>
      <h1>Una tarde por aprovechar</h1>
      <p className="muted">
        {date} · {h}:00–{h + 1}:00
      </p>
      {!data && <p className="muted">Cargando…</p>}
      {data && !slot && <p className="card note">El sensor no registró grupos en esta franja.</p>}
      {slot && (
        <>
          <div className="kpis">
            <div className="kpi">
              <b>{eur(slot.loss_eur)}</b>
              <span>pérdida estimada</span>
            </div>
            <div className="kpi">
              <b>{curve ? Math.round(curve.mean).toLocaleString("es-ES") : "—"}</b>
              <span>peatones/h en la estación (patrón)</span>
            </div>
          </div>
          <table className="tbl">
            <thead>
              <tr>
                <th>Público</th>
                <th>Pasan</th>
                <th>Entran</th>
                <th>Potencial</th>
                <th>Pérdida</th>
              </tr>
            </thead>
            <tbody>
              {segs.map((s) => (
                <tr key={s.segment}>
                  <td>
                    <i className="dot" style={{ background: SEGMENTS[s.segment]?.color }} /> {SEGMENTS[s.segment]?.label}
                  </td>
                  <td>{s.exposed}</td>
                  <td>{s.entering}</td>
                  <td>{s.potential}</td>
                  <td>{eur(s.loss_eur)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Potencial = grupos que pasan × conversión de referencia del segmento. Pérdida = (potencial − entradas) × ticket medio.
          </p>
        </>
      )}
      {rec && (
        <div className="card">
          <h2>¿Qué oferta encaja?</h2>
          <p>
            Público dominante: <b>{SEGMENTS[rec.dominant_segment]?.label || "—"}</b> · grupos impares: <b>{Math.round(rec.odd_share * 100)} %</b>
          </p>
          {rec.offer ? (
            <p>
              Recomendada: <b>{rec.title}</b> ({rec.trials} pruebas previas en esta franja; tasa de éxito estimada {Math.round(rec.posterior_mean * 100)} %)
            </p>
          ) : (
            <p>Ninguna oferta del catálogo encaja con tus preferencias.</p>
          )}
          {rec.excluded?.length > 0 && (
            <details>
              <summary>Ofertas descartadas y por qué</summary>
              <ul className="list">
                {rec.excluded.map((e) => (
                  <li key={e.offer}>
                    {e.offer}: {e.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <div className="card">
        <h2>Alrededor</h2>
        <h3>Eventos cerca ese día</h3>
        {!events ? (
          <p className="muted">…</p>
        ) : events.items.length === 0 ? (
          <p className="muted small">Ninguno en 800 m.</p>
        ) : (
          <ul className="list small">
            {events.items.slice(0, 5).map((e) => (
              <li key={e.event_id}>
                {e.hour || ""} {e.title} · {e.venue} ({e.distance_m} m)
              </li>
            ))}
          </ul>
        )}
        <h3>Aparcamientos (ocupación en tiempo real)</h3>
        {!parkings ? (
          <p className="muted">…</p>
        ) : (
          <ul className="list small">
            {parkings.items.slice(0, 4).map((p) => (
              <li key={p.id}>
                {p.name} ({p.distance_m} m): {p.free_spaces != null ? `${p.free_spaces} libres` : "sin dato en vivo"}
                {p.occupancy_pct != null && ` · ${p.occupancy_pct} % ocupado`}
              </li>
            ))}
          </ul>
        )}
        <p className="muted small">Fuente: datos.madrid.es (agenda de actividades; aparcamientos públicos en tiempo real).</p>
      </div>
    </section>
  );
}

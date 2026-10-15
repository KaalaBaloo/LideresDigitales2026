import { useEffect, useState } from "react";
import { api, eur, fmtDate, pct } from "../api.js";
import { useShop } from "../App.jsx";

const TARGET = 0.1;

export default function Learnings() {
  const { shop } = useShop();
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = () => api.campaigns(shop.id).then(setRows);
  useEffect(() => {
    load();
  }, [shop.id]);

  const close = async (id) => {
    setBusy(id);
    try {
      await api.closeCampaign(id);
      await load();
    } finally {
      setBusy(null);
    }
  };

  if (!rows) return <p className="muted">Cargando…</p>;
  const done = rows.filter((r) => r.success != null);
  const ok = done.filter((r) => r.success);
  const byOffer = {};
  for (const r of done) {
    const o = (byOffer[r.offer_type] ||= { n: 0, ok: 0, up: [] });
    o.n += 1;
    o.ok += r.success ? 1 : 0;
    o.up.push(r.uplift);
  }

  return (
    <section>
      <h1>Cada campaña enseña</h1>
      <p className="muted">Aprendizajes · resultados y próximas decisiones</p>
      <div className="kpis">
        <div className="kpi">
          <b>
            {ok.length} de {done.length}
          </b>
          <span>campañas exitosas (objetivo ≥ {Math.round(TARGET * 100)} % de conversión)</span>
        </div>
      </div>
      <p className="muted small">
        Éxito = uplift de conversión (entradas / grupos que pasan) frente a franjas comparables sin promo: mismo día de la semana y horas, semanas
        anteriores. No demuestra causalidad: no hay grupo de control. Historial simulado.
      </p>

      <div className="card">
        <h2>Qué funciona por oferta</h2>
        <table className="tbl">
          <thead>
            <tr>
              <th>Oferta</th>
              <th>Pruebas</th>
              <th>Éxitos</th>
              <th>Uplift medio</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(byOffer).map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td>{v.n}</td>
                <td>{v.ok}</td>
                <td>{pct(v.up.reduce((a, b) => a + b, 0) / v.up.length)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Historial de resultados</h2>
      {rows.map((r) => {
        const b = r.baseline || {};
        return (
          <div key={r.id} className={`card camp ${r.success === true ? "good" : r.success === false ? "bad" : ""}`}>
            <div className="row between">
              <b>
                {fmtDate(r.starts_at)} · {r.starts_at.slice(11, 16)}–{r.ends_at.slice(11, 16)} · {r.offer_type}
              </b>
              <span className="badge">{r.success == null ? (r.status === "active" ? "en curso" : "sin base") : pct(r.uplift)}</span>
            </div>
            <div className="small muted">
              {r.context?.dominant_segment && `Público dominante: ${r.context.dominant_segment} · `}
              grupos impares {Math.round((r.context?.odd_share || 0) * 100)} %
              {r.context?.weather?.temp_max != null && ` · ${r.context.weather.temp_max} ºC`}
              {r.context?.event_nearby && ` · evento cerca: ${r.context.event_nearby.title}`}
            </div>
            {b.promo_entries != null && (
              <div className="small">
                Entradas {Math.round(b.baseline_entries)} → {b.promo_entries} · conversión {(b.baseline_conversion * 100).toFixed(1)} % →{" "}
                {(b.promo_conversion * 100).toFixed(1)} %{r.revenue != null && ` · ventas ${eur(r.revenue)}`}
              </div>
            )}
            {(r.diagnosis || []).slice(0, 2).map((d) => (
              <p key={d.code} className="small reason">
                {d.text} <span className="muted">({Math.round(d.confidence * 100)} %)</span>
              </p>
            ))}
            {r.status === "active" && (
              <button className="secondary" disabled={busy === r.id} onClick={() => close(r.id)}>
                {busy === r.id ? "Calculando…" : "Cerrar y medir resultado"}
              </button>
            )}
          </div>
        );
      })}
      <p className="muted small">Aprender no es prometer: cada recomendación es una nueva hipótesis que conviene contrastar.</p>
    </section>
  );
}

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, eur, SEGMENTS, today } from "../api.js";
import { useShop } from "../App.jsx";
import DayChart from "../components/DayChart.jsx";

export default function Home() {
  const { shop } = useShop();
  const nav = useNavigate();
  const [date, setDate] = useState(today());
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setData(null);
    api.opportunities(shop.id, date).then(setData).catch((e) => setErr(e.message));
  }, [shop.id, date]);

  return (
    <section>
      <h1>Tu calle, hoy</h1>
      <p className="muted">
        {shop.name} · {shop.street}
      </p>
      <label className="row">
        Día <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      {err && <p className="error">{err}</p>}
      {!data && !err && <p className="muted">Cargando…</p>}
      {data && (
        <>
          {!data.has_sensor_data && (
            <div className="card note">
              Aún no hay datos del sensor para este día.
              {data.latest_date_with_data && (
                <>
                  {" "}
                  <button className="link" onClick={() => setDate(data.latest_date_with_data)}>
                    Ver el último día con datos ({data.latest_date_with_data})
                  </button>
                </>
              )}
            </div>
          )}
          <div className="kpis">
            <div className="kpi">
              <b>{eur(data.summary.total_loss_eur)}</b>
              <span>ventas estimadas sin captar</span>
            </div>
            <div className="kpi">
              <b>{data.summary.worst_hours[0] ? `${data.summary.worst_hours[0].hour}:00` : "—"}</b>
              <span>franja con más pérdida</span>
            </div>
          </div>
          <DayChart hours={data.hours} curve={data.station.curve} onHour={(h) => nav(`/oportunidad/${date}/${h}`)} />
          <p className="muted small">{data.station.note}</p>
          {data.summary.worst_hours.length > 0 && (
            <div className="card">
              <h2>Franjas por aprovechar</h2>
              <ul className="list">
                {data.summary.worst_hours.map((w) => (
                  <li key={w.hour}>
                    <Link to={`/oportunidad/${date}/${w.hour}`}>
                      {w.hour}:00–{w.hour + 1}:00 <b>{eur(w.loss_eur)}</b> →
                    </Link>
                  </li>
                ))}
              </ul>
              <h3>Pérdida por público</h3>
              <ul className="list">
                {Object.entries(data.summary.loss_by_segment).map(([k, v]) => (
                  <li key={k}>
                    <i className="dot" style={{ background: SEGMENTS[k]?.color }} /> {SEGMENTS[k]?.label || k}: <b>{eur(v)}</b>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {data.shadow_effect?.available && data.shadow_effect.shadow_hours.length > 0 && (
            <div className="card shadow">
              <h2>Efecto Sombra</h2>
              <p>
                En las horas pico de la calle principal ({data.shadow_effect.main_station_id}) tu calle capta menos gente de lo habitual
                (ratio normal {(data.shadow_effect.ratio_ref * 100).toFixed(1)} %).
              </p>
              <ul className="list">
                {data.shadow_effect.shadow_hours.slice(0, 3).map((s) => (
                  <li key={s.hour}>
                    {s.hour}:00 · principal {Math.round(s.main_pedestrians)} peatones · captas {(s.capture_ratio * 100).toFixed(1)} % ·
                    déficit ≈ {Math.round(s.deficit)} personas (unid. sensor)
                  </li>
                ))}
              </ul>
              <p className="muted small">Idea: señalización o promo visible en la esquina con la calle principal en esas horas.</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}

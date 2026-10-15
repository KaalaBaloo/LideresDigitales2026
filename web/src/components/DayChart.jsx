import { SEGMENTS } from "../api.js";

/**
 * Curva del día: barras apiladas de grupos vistos por segmento (sensor) + línea de la
 * curva patrón real de la estación de aforo (eje propio) + franjas con pérdida resaltadas.
 */
export default function DayChart({ hours, curve, onHour, selected }) {
  const H = 210, W = 360, padL = 26, padB = 22, padT = 10;
  const allHours = [...new Set([...hours.map((h) => h.hour), ...curve.map((c) => c.hour).filter((h) => h >= 8 && h <= 23)])].sort((a, b) => a - b);
  if (!allHours.length) return <p className="muted">Sin datos para este día.</p>;
  const byHour = Object.fromEntries(hours.map((h) => [h.hour, h]));
  const curveBy = Object.fromEntries(curve.map((c) => [c.hour, c]));
  const totals = allHours.map((h) => Object.values(byHour[h]?.segments || {}).reduce((a, s) => a + s.exposed, 0));
  const maxG = Math.max(1, ...totals);
  const maxP = Math.max(1, ...allHours.map((h) => curveBy[h]?.p70 || curveBy[h]?.mean || 0));
  const maxLoss = Math.max(0, ...allHours.map((h) => byHour[h]?.loss_eur || 0));
  const bw = (W - padL - 4) / allHours.length;
  const y = (v) => H - padB - (v / maxG) * (H - padB - padT);
  const yp = (v) => H - padB - (v / maxP) * (H - padB - padT);
  const x = (i) => padL + i * bw;

  const line = allHours
    .map((h, i) => (curveBy[h] ? `${x(i) + bw / 2},${yp(curveBy[h].mean)}` : null))
    .filter(Boolean)
    .join(" ");
  const band =
    allHours.filter((h) => curveBy[h]).length > 1
      ? allHours.map((h, i) => (curveBy[h] ? `${x(i) + bw / 2},${yp(curveBy[h].p70)}` : null)).filter(Boolean).join(" ") +
        " " +
        allHours.map((h, i) => (curveBy[h] ? `${x(i) + bw / 2},${yp(curveBy[h].p30)}` : null)).filter(Boolean).reverse().join(" ")
      : "";

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Grupos por hora y segmento con la curva de peatones de la estación">
        {allHours.map((h, i) => {
          const loss = byHour[h]?.loss_eur || 0;
          return loss > 0 && maxLoss > 0 ? (
            <rect key={`l${h}`} x={x(i)} y={padT} width={bw} height={H - padB - padT} fill="var(--loss)" opacity={0.08 + 0.3 * (loss / maxLoss)} />
          ) : null;
        })}
        {band && <polygon points={band} fill="var(--ink)" opacity="0.07" />}
        {allHours.map((h, i) => {
          let acc = 0;
          return Object.entries(SEGMENTS).map(([k, s]) => {
            const v = byHour[h]?.segments?.[k]?.exposed || 0;
            if (!v) return null;
            const y0 = y(acc), y1 = y(acc + v);
            acc += v;
            return <rect key={`${h}${k}`} x={x(i) + 2} y={y1} width={bw - 4} height={y0 - y1} fill={s.color} />;
          });
        })}
        {line && <polyline points={line} fill="none" stroke="var(--ink)" strokeWidth="1.6" strokeDasharray="4 3" />}
        {allHours.map((h, i) => (
          <g key={`h${h}`} onClick={() => onHour && onHour(h)} style={{ cursor: onHour ? "pointer" : "default" }}>
            <rect x={x(i)} y={padT} width={bw} height={H - padT} fill="transparent" stroke={selected === h ? "var(--ink)" : "none"} />
            {(i % 2 === 0 || allHours.length < 10) && (
              <text x={x(i) + bw / 2} y={H - 6} fontSize="9" textAnchor="middle" fill="var(--muted)">
                {h}h
              </text>
            )}
          </g>
        ))}
        <text x="2" y={padT + 8} fontSize="8" fill="var(--muted)">{maxG}</text>
        <text x="2" y={H - padB} fontSize="8" fill="var(--muted)">0</text>
      </svg>
      <figcaption>
        <div className="legend">
          {Object.entries(SEGMENTS).map(([k, s]) => (
            <span key={k}><i style={{ background: s.color }} />{s.short}</span>
          ))}
        </div>
        <span className="muted small">
          Barras: grupos vistos por el sensor. Línea discontinua (y banda p30–p70): peatones de la estación de aforo real, patrón histórico.
          Fondo rojo: franjas con pérdida estimada.
        </span>
      </figcaption>
    </figure>
  );
}

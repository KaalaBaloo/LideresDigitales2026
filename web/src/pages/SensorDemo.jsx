import { useEffect, useRef, useState } from "react";
import { api, SEGMENTS } from "../api.js";
import { useShop } from "../App.jsx";

/**
 * Vista "Sensor demo": envía un fotograma de prueba al endpoint de depuración (que lo
 * reenvía al servicio edge y lo descarta) y pinta cajas y grupos. Las personas se
 * difuminan en la vista. Nada de esta imagen se guarda ni llega a un LLM.
 */
export default function SensorDemo() {
  const { shop } = useShop();
  const canvas = useRef(null);
  const [file, setFile] = useState(null);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [evalSum, setEvalSum] = useState(null);

  useEffect(() => {
    api.sensorEval(shop.id).then(setEvalSum).catch(() => {});
  }, [shop.id]);

  const run = async () => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.debugFrame(file, shop.id));
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!file || !canvas.current) return;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const c = canvas.current;
      const scale = Math.min(1, 900 / img.width);
      c.width = img.width * scale;
      c.height = img.height * scale;
      const ctx = c.getContext("2d");
      ctx.filter = "none";
      ctx.drawImage(img, 0, 0, c.width, c.height);
      if (!res) return;
      for (const g of res.groups) {
        const color = SEGMENTS[g.segment]?.color || "#fff";
        let minX = 1, minY = 1, maxX = 0, maxY = 0;
        for (const b of g.boxes) {
          const [x1, y1, x2, y2] = b.box;
          const [px, py, pw, ph] = [x1 * c.width, y1 * c.height, (x2 - x1) * c.width, (y2 - y1) * c.height];
          // difuminado de la persona
          ctx.save();
          ctx.beginPath();
          ctx.rect(px, py, pw, ph);
          ctx.clip();
          ctx.filter = "blur(10px)";
          ctx.drawImage(img, 0, 0, c.width, c.height);
          ctx.restore();
          ctx.strokeStyle = color;
          ctx.lineWidth = b.child ? 1.5 : 2.5;
          ctx.setLineDash(b.child ? [4, 3] : []);
          ctx.strokeRect(px, py, pw, ph);
          minX = Math.min(minX, x1); minY = Math.min(minY, y1); maxX = Math.max(maxX, x2); maxY = Math.max(maxY, y2);
        }
        ctx.setLineDash([]);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.strokeRect(minX * c.width - 4, minY * c.height - 4, (maxX - minX) * c.width + 8, (maxY - minY) * c.height + 8);
        const label = `${SEGMENTS[g.segment]?.short || g.segment} · ${g.adults}A ${g.children}N${g.entering ? " · entra" : ""}`;
        ctx.font = "bold 13px system-ui";
        const w = ctx.measureText(label).width + 8;
        ctx.fillStyle = color;
        ctx.fillRect(minX * c.width - 4, minY * c.height - 22, w, 18);
        ctx.fillStyle = "#fff";
        ctx.fillText(label, minX * c.width, minY * c.height - 8);
      }
      // línea virtual de la puerta
      const door = shop.door_line;
      if (door) {
        ctx.strokeStyle = "#ffd400";
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 6]);
        ctx.beginPath();
        ctx.moveTo(door.p1[0] * c.width, door.p1[1] * c.height);
        ctx.lineTo(door.p2[0] * c.width, door.p2[1] * c.height);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      URL.revokeObjectURL(url);
    };
    img.src = url;
  }, [file, res, shop.door_line]);

  return (
    <section>
      <h1>Sensor demo</h1>
      <p className="muted small">
        Sube un fotograma de prueba (imágenes sintéticas de <code>data/test_frames</code>). Se procesa con un detector de personas preentrenado
        (DETR) en el servicio edge y se descarta: solo vuelven cajas y grupos. Sin reconocimiento facial. Las personas aparecen difuminadas.
      </p>
      <div className="row">
        <input type="file" accept="image/png,image/jpeg" onChange={(e) => { setFile(e.target.files[0] || null); setRes(null); }} />
        <button className="primary" disabled={!file || busy} onClick={run}>
          {busy ? "Detectando…" : "Detectar grupos"}
        </button>
      </div>
      {err && <p className="error">{err}</p>}
      <canvas ref={canvas} className="frame" />
      {res && (
        <div className="card">
          <b>{res.people} personas · {res.groups.length} grupos</b>
          <ul className="list small">
            {res.groups.map((g) => (
              <li key={g.id}>
                <i className="dot" style={{ background: SEGMENTS[g.segment]?.color }} /> {SEGMENTS[g.segment]?.label}: {g.adults} adultos, {g.children} niños
                {g.size % 2 ? " · grupo impar" : ""} · {g.entering ? "entra" : "pasa"}
              </li>
            ))}
          </ul>
          <p className="muted small">Agregados que subiría el dispositivo: {JSON.stringify(res.aggregates)}</p>
        </div>
      )}
      {evalSum?.frames > 0 && (
        <div className="card">
          <h2>Precisión frente al ground truth</h2>
          <p className="small">
            {evalSum.frames} fotogramas · conteo {Math.round(evalSum.count_accuracy * 100)} %
            {evalSum.segment_match != null && ` · segmento ${Math.round(evalSum.segment_match * 100)} %`} · personas reales {evalSum.people_true} vs detectadas{" "}
            {evalSum.people_pred}
          </p>
        </div>
      )}
    </section>
  );
}

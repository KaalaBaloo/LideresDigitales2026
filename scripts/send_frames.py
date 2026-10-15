"""Simula una cámara en tiempo real: envía una imagen cada N segundos al servicio edge.

    python scripts/send_frames.py --edge https://hora-valle-edge.onrender.com --shop 1 \
        --dir data/test_frames --interval 5 --limit 10 [--start 2026-10-20T17:00]

--start fija la hora simulada del primer fotograma (cada fotograma avanza --step-min
minutos) para que la demo caiga en la franja deseada; sin --start se usa la hora actual.
Si existe ground_truth.json en la carpeta, se adjunta la verdad de cada fotograma
y el edge calcula precisión de conteo y de segmentación.
Las imágenes SOLO van al servicio edge (detector); nunca a un LLM.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timedelta

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edge", default=os.environ.get("EDGE_URL", "http://localhost:8001"))
    ap.add_argument("--shop", type=int, default=1)
    ap.add_argument("--dir", default="data/test_frames")
    ap.add_argument("--interval", type=float, default=5.0, help="segundos entre fotogramas")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", help="hora simulada ISO del primer fotograma")
    ap.add_argument("--step-min", type=float, default=2.0)
    ap.add_argument("--key", default=os.environ.get("SENSOR_API_KEY", ""))
    a = ap.parse_args()

    folder = pathlib.Path(a.dir)
    gt_file = folder / "ground_truth.json"
    truth = {}
    if gt_file.exists():
        truth = {f["file"]: f for f in json.loads(gt_file.read_text(encoding="utf-8")).get("frames", []) if not f.get("exclude")}
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if truth:
        files = [p for p in files if p.name in truth]
    if a.limit:
        files = files[: a.limit]
    if not files:
        print("No hay imágenes en", folder, file=sys.stderr)
        return 2

    start = datetime.fromisoformat(a.start) if a.start else None
    client = httpx.Client(timeout=180)
    # despierta el servicio (plan gratuito de Render)
    try:
        client.get(f"{a.edge}/health")
    except httpx.HTTPError:
        pass
    acc = []
    for i, p in enumerate(files):
        data = {"shop_id": str(a.shop), "frame_name": p.name}
        if start:
            data["ts"] = (start + timedelta(minutes=i * a.step_min)).isoformat(timespec="seconds")
        if p.name in truth:
            data["truth"] = json.dumps(truth[p.name])
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        t0 = time.time()
        try:
            r = client.post(f"{a.edge}/edge/frames", data=data, files={"image": (p.name, p.read_bytes(), mime)}, headers={"X-Sensor-Key": a.key})
            r.raise_for_status()
            sent = r.json()["sent"]
            ev = sent.get("eval", {})
            if "count_accuracy" in ev:
                acc.append(ev)
            segs = ", ".join(f"{x['segment']}:{x.get('groups_passing', 0)}p/{x.get('groups_entering', 0)}e" for x in sent["aggregates"]) or "sin personas"
            print(f"[{i + 1}/{len(files)}] {p.name} -> {segs}  {ev}")
        except httpx.HTTPError as e:
            print(f"[{i + 1}/{len(files)}] {p.name} ERROR {e} {getattr(e, 'response', None) and e.response.text[:200]}")
        if i < len(files) - 1:
            time.sleep(max(0.0, a.interval - (time.time() - t0)))
    if acc:
        ca = sum(e["count_accuracy"] for e in acc) / len(acc)
        sm = [e["segment_match"] for e in acc if "segment_match" in e]
        print(f"\nPrecisión media de conteo: {ca:.2f}" + (f" · coincidencia de segmento: {sum(sm) / len(sm):.2f}" if sm else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

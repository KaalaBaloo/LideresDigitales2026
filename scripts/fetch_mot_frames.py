"""Plan B: descarga 20 fotogramas REALES de MOT20 desde un espejo en Hugging Face,
sin bajar el dataset completo (hf_hub_download fichero a fichero).

Espejo verificado el 15-oct-2026: dataset `Lekim89/MOT20` (no restringido),
ruta train/MOT20-01/img1/NNNNNN.jpg y anotaciones train/MOT20-01/gt/gt.txt.
Licencia MOTChallenge: CC BY-NC-SA 3.0 — solo uso académico/no comercial, con
atribución. Por eso los fotogramas NO se versionan en el repo (data/mot_frames está ignorado).

    python scripts/fetch_mot_frames.py [--n 20] [--seq MOT20-01]
Escribe data/mot_frames/ground_truth.json con el nº de peatones visibles por fotograma
(MOT no etiqueta grupos ni niños: solo se evalúa el conteo).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
from collections import Counter

from huggingface_hub import hf_hub_download

REPO = "Lekim89/MOT20"
OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "mot_frames"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seq", default="MOT20-01")
    ap.add_argument("--stride", type=int, default=20, help="separación entre fotogramas elegidos")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    gt_txt = hf_hub_download(REPO, f"train/{a.seq}/gt/gt.txt", repo_type="dataset")
    people = Counter()
    for line in open(gt_txt, encoding="utf-8"):
        f, _id, _x, _y, _w, _h, considered, cls, vis = line.strip().split(",")[:9]
        if int(considered) == 1 and int(cls) == 1 and float(vis) >= 0.25:  # peatón visible
            people[int(f)] += 1

    frames = []
    for k in range(a.n):
        idx = 1 + k * a.stride
        src = hf_hub_download(REPO, f"train/{a.seq}/img1/{idx:06d}.jpg", repo_type="dataset")
        name = f"{a.seq}_{idx:06d}.jpg"
        shutil.copy(src, OUT / name)
        frames.append({"file": name, "people": people[idx], "groups": None, "synthetic": False, "source": f"{REPO}:{a.seq}"})
        print("ok", name, people[idx], "peatones")
    (OUT / "ground_truth.json").write_text(
        json.dumps({"source": REPO, "license": "CC BY-NC-SA 3.0 (MOTChallenge)", "frames": frames}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

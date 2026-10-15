"""Genera ~30 imágenes SINTÉTICAS de cámara con FLUX.1-schnell (Apache-2.0) vía
Hugging Face Inference Providers y escribe data/test_frames/ground_truth.json.

Ejecútalo UNA sola vez (consume créditos) y versiona el resultado:
    HF_TOKEN=hf_xxx python scripts/generate_test_frames.py
Después revisa las etiquetas:  python scripts/review_ground_truth.py

Privacidad / licencias: las imágenes no contienen personas reales y NUNCA se envían
a Claude ni a ningún LLM: solo al detector de personas del servicio edge.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

MODEL = "black-forest-labs/FLUX.1-schnell"
OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "test_frames"

PROMPT = (
    "CCTV-style photo from a shop camera mounted 3 meters high, looking at a busy pedestrian "
    "shopping street in central Madrid, Spain, afternoon light, {GRUPO} walking together on the "
    "sidewalk, other pedestrians in background, realistic, slightly low resolution"
)

# categoría -> (texto {GRUPO}, grupos esperados en primer plano)
CATEGORIES = {
    "solo": ("one adult walking alone", [{"segment": "solo", "adults": 1, "children": 0}]),
    "dos_adultos": ("two adults walking side by side", [{"segment": "dos_adultos", "adults": 2, "children": 0}]),
    "adulto_con_ninos": (
        "two adults with one small child and a baby stroller",
        [{"segment": "adulto_con_ninos", "adults": 2, "children": 1}],
    ),
    "familia_numerosa": ("two adults with four young children", [{"segment": "familia_numerosa", "adults": 2, "children": 4}]),
    "grupo_adultos_3_6": ("a group of three young adult friends", [{"segment": "grupo_adultos_3_6", "adults": 3, "children": 0}]),
    "mixta": (
        "a family with two children and, separately, a group of four friends",
        [
            {"segment": "adulto_con_ninos", "adults": 2, "children": 2},
            {"segment": "grupo_adultos_3_6", "adults": 4, "children": 0},
        ],
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=5)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--provider", default=os.environ.get("HF_IMAGE_PROVIDER", "auto"),
                    help="FLUX.1-schnell NO está en hf-inference; activo en fal-ai y wavespeed (15-oct-2026)")
    ap.add_argument("--force", action="store_true", help="regenera aunque ya existan (gasta créditos)")
    a = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("Falta HF_TOKEN (permiso 'Inference Providers').", file=sys.stderr)
        return 2
    from huggingface_hub import InferenceClient

    client = InferenceClient(provider=a.provider, api_key=token)
    OUT.mkdir(parents=True, exist_ok=True)
    gt_path = OUT / "ground_truth.json"
    gt = json.loads(gt_path.read_text(encoding="utf-8")) if gt_path.exists() else {"frames": []}
    by_file = {f["file"]: f for f in gt["frames"]}

    for cat, (grupo, groups) in CATEGORIES.items():
        for i in range(1, a.per_category + 1):
            name = f"{cat}_{i:02d}.png"
            path = OUT / name
            if path.exists() and not a.force:
                print("ya existe", name)
                continue
            seed = 1000 * (list(CATEGORIES).index(cat) + 1) + i  # reproducible
            prompt = PROMPT.format(GRUPO=grupo)
            for attempt in range(3):
                try:
                    img = client.text_to_image(prompt, model=MODEL, width=a.width, height=a.height, num_inference_steps=4, seed=seed)
                    break
                except Exception as e:  # cola del proveedor / límites de uso
                    print(f"  reintento {attempt + 1} {name}: {e}")
                    time.sleep(5 * (attempt + 1))
            else:
                print("FALLO", name)
                continue
            img.save(path)
            by_file[name] = {
                "file": name,
                "category": cat,
                "prompt": prompt,
                "seed": seed,
                "model": MODEL,
                "provider": a.provider,
                "groups": groups,
                "reviewed": False,
                "synthetic": True,
            }
            print("ok", name)

    gt = {
        "generator": MODEL,
        "license": "Apache-2.0 (modelo). Imágenes sintéticas sin personas reales.",
        "note": "Etiquetas = lo pedido en el prompt. Revísalas: el generador a veces falla en el nº de personas.",
        "frames": sorted(by_file.values(), key=lambda f: f["file"]),
    }
    gt_path.write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(gt['frames'])} fotogramas en {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

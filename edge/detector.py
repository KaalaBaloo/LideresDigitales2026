"""Detector de personas tras una interfaz intercambiable.

Prototipo: DETR (facebook/detr-resnet-50) vía Hugging Face Inference Providers.
Producción: YOLO ejecutándose en el dispositivo de la tienda sobre el stream.

Restricción de licencia: las imágenes solo pasan por un modelo de DETECCIÓN
preentrenado. Nunca se envían a modelos generativos/multimodales ni se usan para
entrenar o hacer fine-tuning.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    label: str = "person"

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def foot(self) -> tuple[float, float]:
        """Punto de apoyo: centro del borde inferior de la caja."""
        return ((self.x1 + self.x2) / 2.0, self.y2)


class Detector(Protocol):
    name: str

    def detect(self, image: bytes) -> list[Detection]:
        """Devuelve solo detecciones de personas en píxeles de la imagen."""


class HFDetrDetector:
    name = "hf-detr"

    def __init__(self, token: str, model: str = "facebook/detr-resnet-50", provider: str = "hf-inference", threshold: float = 0.7):
        from huggingface_hub import InferenceClient

        self.client = InferenceClient(provider=provider, api_key=token)
        self.model = model
        self.threshold = threshold

    def detect(self, image: bytes) -> list[Detection]:
        out = self.client.object_detection(image, model=self.model, threshold=self.threshold)
        return [
            Detection(float(o.box.xmin), float(o.box.ymin), float(o.box.xmax), float(o.box.ymax), float(o.score), o.label)
            for o in out
            if o.label == "person" and o.score >= self.threshold
        ]


class YoloEdgeDetector:
    """Hueco para producción: YOLO (p. ej. ultralytics / ONNX Runtime) en el dispositivo."""

    name = "yolo-edge"

    def __init__(self, weights: str, threshold: float = 0.5):
        self.weights = weights
        self.threshold = threshold

    def detect(self, image: bytes) -> list[Detection]:  # pragma: no cover - no se usa en el prototipo
        raise NotImplementedError("YOLO en dispositivo: ver docs/ARQUITECTURA.md §6")


class StaticDetector:
    """Detector de pruebas: devuelve detecciones fijas (tests y modo sin token)."""

    name = "static"

    def __init__(self, detections: list[Detection]):
        self.detections = detections

    def detect(self, image: bytes) -> list[Detection]:
        return list(self.detections)

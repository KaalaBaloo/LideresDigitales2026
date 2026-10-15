"""Módulo enchufable de rango de edad por CUERPO (nunca por cara). Desactivado por defecto.

Búsqueda en Hugging Face (15-oct-2026):
  * NTQAI/pedestrian_age_recognition (image-classification, Apache-2.0): recortes de
    peatón de cuerpo entero -> rango de edad. SIN Inference Provider (no usable por API).
  * Awiros/person-attribute-recognition (ONNX, licencia "other"): SIN Inference Provider.
Conclusión: se deja la interfaz con un stub. Trabajo futuro: ejecutar el modelo
ONNX en el propio dispositivo sobre el recorte de cada caja, devolviendo solo una
etiqueta agregada (p. ej. 'joven', 'adulto', 'mayor') y nunca el recorte.
"""
from __future__ import annotations

from typing import Protocol


class AgeBandEstimator(Protocol):
    enabled: bool

    def annotate(self, groups: list) -> None:
        """Añade a cada grupo un atributo `age_bands: Counter` (solo agregados)."""


class DisabledAgeBand:
    enabled = False

    def annotate(self, groups: list) -> None:
        return None


class OnDeviceAgeBand:  # pragma: no cover - trabajo futuro
    enabled = True

    def __init__(self, onnx_path: str):
        raise NotImplementedError("age_band en dispositivo: ver docs/ARQUITECTURA.md §8")

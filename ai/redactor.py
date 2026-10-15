"""Redactor de la notificación al comerciante (español, ≤ 60 palabras).

Entrada: SOLO el JSON estructurado de diagnóstico + recomendación. Nunca imágenes
ni datos personales. Si no hay ANTHROPIC_API_KEY, si Claude rechaza la petición o
si el texto no supera la validación (longitud, cifras que no estén en el JSON),
se usa una plantilla determinista.
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

MAX_WORDS = 60
DEFAULT_MODEL = "claude-opus-5-5"
# Modelos que aceptan el parámetro server-side `fallbacks: "default"` en la API de Claude
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

SYSTEM = (
    "Eres el asistente de una app para pequeños comercios de Madrid. Escribe UNA notificación "
    "en español de España, de tú, cercana y concreta, de 60 palabras como máximo, para el dueño "
    "de la tienda. Usa exclusivamente los datos del JSON: no inventes cifras, horas, porcentajes "
    "ni importes que no aparezcan literalmente en él, y no hagas promesas de resultados. "
    "Estructura: la oportunidad (franja y público), por qué (diagnóstico más fiable) y la "
    "oferta recomendada con su nombre tal cual. Responde solo con el texto de la notificación, "
    "sin comillas, sin markdown y sin saludo."
)

SEGMENT_LABELS = {
    "solo": "personas solas",
    "dos_adultos": "parejas",
    "adulto_con_ninos": "adultos con niños",
    "familia_numerosa": "familias numerosas",
    "grupo_adultos_3_6": "grupos de 3 a 6 adultos",
    "grupo_grande": "grupos grandes",
}

_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[str]:
    """Cifras normalizadas (coma o punto decimal, sin ceros finales)."""
    out = set()
    for n in _NUM.findall(text):
        n = n.replace(",", ".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n.lstrip("0") or "0")  # '00' de '18:00' -> '0'
    out.discard("0")  # el cero (y los minutos ':00') nunca es una cifra inventada
    return out


def allowed_numbers(payload: dict) -> set[str]:
    raw = json.dumps(payload, ensure_ascii=False)
    nums = _numbers(raw)
    # también se permiten los porcentajes de fracciones (0.43 -> 43) y enteros de importes redondeados
    for n in list(nums):
        try:
            v = float(n)
        except ValueError:
            continue
        if 0 < v < 1:
            nums.add(str(round(v * 100)))
        nums.add(str(round(v)))
    return nums


def validate(text: str, payload: dict) -> list[str]:
    problems = []
    words = len(text.split())
    if words > MAX_WORDS:
        problems.append(f"{words} palabras (> {MAX_WORDS})")
    extra = _numbers(text) - allowed_numbers(payload)
    if extra:
        problems.append(f"cifras no presentes en el JSON: {sorted(extra)}")
    return problems


def template(payload: dict) -> str:
    opp = payload.get("opportunity", {})
    rec = payload.get("recommendation", {})
    diag = payload.get("diagnosis") or []
    seg = SEGMENT_LABELS.get(opp.get("segment"), opp.get("segment") or "tu público")
    parts = [f"A las {opp.get('hour')}:00 pasan sobre todo {seg}, pero casi no entran."]
    if opp.get("loss_eur"):
        parts.append(f"Estimamos {opp['loss_eur']:.0f} € en ventas sin captar.")
    if diag:
        parts.append(diag[0]["text"])
    if rec.get("title"):
        parts.append(f"Prueba: «{rec['title']}».")
    text = " ".join(parts)
    words = text.split()
    return " ".join(words[:MAX_WORDS])


def compose(payload: dict, api_key: str | None = None, model: str | None = None) -> tuple[str, str]:
    """Devuelve (texto, fuente) con fuente 'claude' o 'template'."""
    api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return template(payload), "template"
    model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=2)
        kwargs = dict(
            model=model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            output_config={"effort": "low"},
        )
        if model in _FALLBACK_MODELS:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            log.warning("Claude rechazó la redacción (%s); uso plantilla", getattr(resp.stop_details, "category", None))
            return template(payload), "template"
        text = " ".join(b.text for b in resp.content if b.type == "text").strip().strip('"«»')
        problems = validate(text, payload)
        if problems or not text:
            log.warning("Texto de Claude descartado: %s", problems or "vacío")
            return template(payload), "template"
        return text, "claude"
    except Exception as e:  # red, cuota, credenciales: la app nunca se queda sin aviso
        log.warning("Redactor Claude no disponible (%s); uso plantilla", type(e).__name__)
        return template(payload), "template"

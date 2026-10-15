"""Precisión frente al ground truth de las imágenes de prueba.

Formato de una entrada de data/test_frames/ground_truth.json:
  {"file": "dos_adultos_01.png", "category": "dos_adultos",
   "groups": [{"segment": "dos_adultos", "adults": 2, "children": 0}], "reviewed": true}
Para fotogramas MOT (plan B) solo hay recuento: {"file": ..., "people": 37, "groups": null}.
"""
from __future__ import annotations

from collections import Counter

from .grouping import Group


def evaluate(groups: list[Group], truth: dict) -> dict:
    pred_people = sum(g.size for g in groups)
    t_groups = truth.get("groups")
    true_people = truth.get("people")
    if true_people is None and t_groups:
        true_people = sum(int(g.get("adults", 0)) + int(g.get("children", 0)) for g in t_groups)
    out: dict = {"count_true": true_people, "count_pred": pred_people}
    if true_people:
        out["count_accuracy"] = round(max(0.0, 1 - abs(pred_people - true_people) / true_people), 3)
    if t_groups:
        tc = Counter(g["segment"] for g in t_groups)
        pc = Counter(g.segment for g in groups)
        hits = sum((tc & pc).values())
        out["segment_match"] = round(hits / max(sum(tc.values()), sum(pc.values())), 3)
    return out

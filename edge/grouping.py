"""Agrupación de personas, niño/adulto y segmento de grupo.

1. Punto de apoyo = centro inferior de cada caja.
2. DBSCAN con eps = eps_factor × altura mediana de las cajas (corrige la escala
   por perspectiva: en planos más lejanos las personas y sus separaciones encogen).
3. Niño: altura < child_ratio × mediana de los adultos de su grupo cuyos pies
   están a la misma altura de imagen.
4. Segmento a partir del nº de adultos y niños.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

import numpy as np

from .detector import Detection

SEGMENTS = ("solo", "dos_adultos", "adulto_con_ninos", "familia_numerosa", "grupo_adultos_3_6", "grupo_grande")


@dataclass
class Group:
    members: list[Detection]
    children: list[bool] = field(default_factory=list)
    entering: bool = False

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def n_children(self) -> int:
        return sum(self.children)

    @property
    def n_adults(self) -> int:
        return self.size - self.n_children

    @property
    def segment(self) -> str:
        return segment_of(self.n_adults, self.n_children)

    @property
    def foot(self) -> tuple[float, float]:
        xs = [d.foot[0] for d in self.members]
        ys = [d.foot[1] for d in self.members]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


def dbscan(points: np.ndarray, eps: float, min_samples: int = 1) -> np.ndarray:
    """DBSCAN mínimo (sin dependencias pesadas, apto para el dispositivo edge).

    Devuelve etiquetas de clúster; -1 = ruido (solo posible con min_samples > 1).
    """
    n = len(points)
    labels = np.full(n, -1, dtype=int)
    if n == 0:
        return labels
    d = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=-1)
    neigh = [np.flatnonzero(d[i] <= eps) for i in range(n)]
    core = np.array([len(nb) >= min_samples for nb in neigh])
    cid = 0
    for i in range(n):
        if labels[i] != -1 or not core[i]:
            continue
        labels[i] = cid
        stack = list(neigh[i])
        while stack:
            j = stack.pop()
            if labels[j] == -1:
                labels[j] = cid
                if core[j]:
                    stack.extend(k for k in neigh[j] if labels[k] == -1)
        cid += 1
    return labels


def classify_children(members: list[Detection], child_ratio: float = 0.65, foot_tol: float = 0.25) -> list[bool]:
    """Marca como niño a quien mide < child_ratio × mediana de los adultos con el pie a su altura.

    Los adultos de referencia se estiman en dos pasos: primero, quienes alcanzan
    child_ratio × la caja más alta comparable; después, su mediana.
    Una persona sola siempre se considera adulta (no hay referencia).
    """
    if len(members) < 2:
        return [False] * len(members)
    flags = []
    for p in members:
        peers = [q for q in members if abs(q.foot[1] - p.foot[1]) <= foot_tol * max(q.height, p.height)]
        tallest = max(q.height for q in peers)
        adults = [q.height for q in peers if q.height >= child_ratio * tallest]
        ref = median(adults)
        flags.append(p.height < child_ratio * ref)
    if all(flags):  # salvaguarda: siempre hay al menos un adulto de referencia
        flags[max(range(len(members)), key=lambda i: members[i].height)] = False
    return flags


def segment_of(n_adults: int, n_children: int) -> str:
    size = n_adults + n_children
    if n_children >= 3:
        return "familia_numerosa"
    if n_children >= 1 and size >= 2:
        return "adulto_con_ninos"
    if size == 1:
        return "solo"
    if size == 2:
        return "dos_adultos"
    if size <= 6:
        return "grupo_adultos_3_6"
    return "grupo_grande"


def group_people(dets: list[Detection], eps_factor: float = 0.6, child_ratio: float = 0.65) -> list[Group]:
    if not dets:
        return []
    h_med = median(d.height for d in dets)
    pts = np.array([d.foot for d in dets], dtype=float)
    labels = dbscan(pts, eps=eps_factor * h_med, min_samples=1)
    groups = []
    for lab in sorted(set(labels.tolist())):
        members = [d for d, l in zip(dets, labels) if l == lab]
        groups.append(Group(members=members, children=classify_children(members, child_ratio)))
    return groups

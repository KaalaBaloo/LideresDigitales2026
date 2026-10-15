import io

import numpy as np
from PIL import Image

from edge.detector import Detection, StaticDetector
from edge.evaluate import evaluate
from edge.grouping import classify_children, dbscan, group_people, segment_of
from edge.pipeline import DoorLine, process_frame


def person(x, foot_y, h, w=None):
    w = w or h * 0.35
    return Detection(x - w / 2, foot_y - h, x + w / 2, foot_y, 0.95)


def test_dbscan_two_clusters_and_singleton():
    pts = np.array([[0, 0], [1, 0], [0.5, 0.5], [10, 10], [10.5, 10], [30, 0]])
    lab = dbscan(pts, eps=1.2)
    assert lab[0] == lab[1] == lab[2]
    assert lab[3] == lab[4] != lab[0]
    assert len(set(lab.tolist())) == 3


def test_eps_scales_with_box_height_perspective():
    # Mismo patrón (dos personas a 0.5 alturas de distancia) cerca y lejos de la cámara
    near = [person(100, 700, 300), person(250, 700, 300)]
    far = [person(600, 300, 100), person(650, 300, 100)]
    groups = group_people(near, eps_factor=0.6)
    assert len(groups) == 1 and groups[0].size == 2
    # Separados 4 alturas -> grupos distintos
    apart = [person(100, 700, 300), person(1300, 700, 300)]
    assert len(group_people(apart, eps_factor=0.6)) == 2
    assert len(group_people(far, eps_factor=0.6)) == 1


def test_child_detection_same_foot_level():
    adult1, adult2 = person(100, 500, 200), person(160, 505, 190)
    child = person(130, 500, 110)  # 110 < 0.65 * 195
    flags = classify_children([adult1, adult2, child])
    assert flags == [False, False, True]


def test_far_adult_is_not_child_when_feet_differ():
    near_adult = person(100, 700, 300)
    far_adult = person(110, 450, 150)  # más pequeño por perspectiva, pie mucho más arriba
    assert classify_children([near_adult, far_adult]) == [False, False]


def test_single_parent_with_children_keeps_one_adult():
    flags = classify_children([person(100, 500, 200), person(140, 500, 100), person(170, 500, 95)])
    assert flags == [False, True, True]


def test_segments():
    assert segment_of(1, 0) == "solo"
    assert segment_of(2, 0) == "dos_adultos"
    assert segment_of(1, 1) == "adulto_con_ninos"
    assert segment_of(2, 3) == "familia_numerosa"
    assert segment_of(3, 0) == "grupo_adultos_3_6"
    assert segment_of(6, 0) == "grupo_adultos_3_6"
    assert segment_of(7, 0) == "grupo_grande"


def test_door_line_sides():
    door = DoorLine((0.2, 0.6), (0.6, 0.6), "below")
    assert door.is_inside(0.4, 0.7)
    assert not door.is_inside(0.4, 0.5)
    assert not door.is_inside(0.9, 0.7)  # fuera del tramo de la puerta


def _png(w=1000, h=800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h)).save(buf, format="PNG")
    return buf.getvalue()


def test_pipeline_aggregates_only_counts():
    dets = [
        person(100, 400, 200), person(160, 400, 200), person(220, 400, 200),  # trío que pasa
        person(700, 750, 250), person(780, 750, 240), person(740, 750, 120),  # familia que entra
    ]
    res = process_frame(_png(), StaticDetector(dets), DoorLine((0.5, 0.7), (1.0, 0.7), "below"))
    agg = {a["segment"]: a for a in res.aggregates}
    assert agg["grupo_adultos_3_6"]["groups_passing"] == 1
    assert agg["grupo_adultos_3_6"]["odd_groups"] == 1
    assert agg["adulto_con_ninos"]["groups_entering"] == 1
    assert agg["adulto_con_ninos"]["people_entering"] == 3
    # Los agregados no contienen coordenadas ni nada por persona
    assert all(set(a) <= {"segment", "groups_passing", "groups_entering", "people_passing", "people_entering", "odd_groups"} for a in res.aggregates)
    view = res.debug_view()
    assert view["people"] == 6 and all(0 <= v <= 1 for g in view["groups"] for b in g["boxes"] for v in b["box"])


def test_evaluate_against_ground_truth():
    groups = group_people([person(100, 400, 200), person(160, 400, 200)])
    ev = evaluate(groups, {"groups": [{"segment": "dos_adultos", "adults": 2, "children": 0}]})
    assert ev["count_accuracy"] == 1.0 and ev["segment_match"] == 1.0
    ev2 = evaluate(groups, {"people": 4, "groups": None})
    assert ev2["count_accuracy"] == 0.5 and "segment_match" not in ev2

import random
from datetime import date

import pytest

from ai import bandit, opportunity, rules
from ai.bandit import Arm
from ai.engine import build_payload
from ai.memory import SlotStats, uplift
from ai.redactor import compose, template, validate

CONV = {"dos_adultos": 0.10, "grupo_adultos_3_6": 0.08, "adulto_con_ninos": 0.12}
TICKET = {"dos_adultos": 20.0, "grupo_adultos_3_6": 35.0, "adulto_con_ninos": 28.0}


# ------------------------------------------------------------------ detector de oportunidad
def test_opportunity_formula():
    obs = [{"hour": 18, "segment": "grupo_adultos_3_6", "groups_passing": 90, "groups_entering": 10}]
    (o,) = opportunity.detect(obs, CONV, TICKET)
    assert o.exposed == 100
    assert o.potential == pytest.approx(8.0)  # 100 × 0.08
    assert o.lost_groups == 0  # entran 10 > potencial 8
    obs[0]["groups_entering"] = 3
    (o,) = opportunity.detect(obs, CONV, TICKET)
    assert o.potential == pytest.approx(93 * 0.08)
    assert o.loss_eur == pytest.approx((93 * 0.08 - 3) * 35.0)


def test_opportunity_unknown_segment_has_no_loss():
    (o,) = opportunity.detect([{"hour": 9, "segment": "grupo_grande", "groups_passing": 5}], CONV, TICKET)
    assert o.loss_eur == 0


def test_summary_and_dominant_and_odd_share():
    obs = [
        {"hour": 17, "segment": "dos_adultos", "groups_passing": 10, "groups_entering": 0, "odd_groups": 0},
        {"hour": 18, "segment": "grupo_adultos_3_6", "groups_passing": 30, "groups_entering": 0, "odd_groups": 20},
        {"hour": 18, "segment": "dos_adultos", "groups_passing": 10, "groups_entering": 0, "odd_groups": 0},
    ]
    s = opportunity.summarize(opportunity.detect(obs, CONV, TICKET))
    assert s["worst_hours"][0]["hour"] == 18
    seg, share = opportunity.dominant_segment(obs, 18)
    assert seg == "grupo_adultos_3_6" and share == pytest.approx(0.75)
    sh, odd, tot = opportunity.odd_share([o for o in obs if o["hour"] == 18])
    assert (odd, tot) == (20, 40) and sh == 0.5


def test_shadow_effect_flags_peak_hours_with_low_capture():
    main = {h: v for h, v in zip(range(10, 21), [300, 400, 600, 900, 1000, 800, 700, 900, 1400, 1500, 1000])}
    # la lateral capta ~5 % salvo en el pico de 18-19 h, donde se queda en ~2 %
    side = {h: main[h] * 0.05 for h in main}
    side[18], side[19] = 1400 * 0.02, 1500 * 0.02
    r = opportunity.shadow_effect(main, side)
    assert r["available"]
    hours = [p["hour"] for p in r["shadow_hours"]]
    assert set(hours) >= {18, 19}
    assert r["shadow_hours"][0]["deficit"] > 0


def test_shadow_effect_needs_data():
    assert not opportunity.shadow_effect({10: 100}, {10: 5})["available"]


def test_franjas():
    assert opportunity.franja_of(11) == "manana"
    assert opportunity.franja_of(18) == "tarde"
    assert opportunity.franja_of(3) == "madrugada"


# ------------------------------------------------------------------ memoria / uplift
def test_uplift_uses_conversion_not_raw_sales():
    # Más entradas en la promo, pero también mucha más gente: la conversión no mejora
    promo = SlotStats(exposed=200, entering=20, revenue=400, purchases=20)
    base = [SlotStats(100, 10, 200, 10), SlotStats(100, 10, 220, 10)]
    u = uplift(promo, base)
    assert u["uplift"] == pytest.approx(0.0)
    assert u["success"] is False
    assert u["entries_change"] == pytest.approx(1.0)


def test_uplift_success_threshold():
    u = uplift(SlotStats(100, 13), [SlotStats(100, 10)])
    assert u["uplift"] == pytest.approx(0.3) and u["success"] is True
    assert uplift(SlotStats(100, 10), [])["success"] is None


# ------------------------------------------------------------------ reglas
CAT = bandit.load_catalog()


def test_rule_even_offer_with_odd_groups():
    ctx = {"offer": CAT["2x1"], "context": {"odd_share": 0.62}, "result": {"success": False}}
    out = rules.diagnose(ctx)
    assert out[0]["code"] == "OFERTA_PARES_GRUPOS_IMPARES"
    assert out[0]["evidence"]["odd_pct"] == 62
    assert "62 %" in out[0]["text"]
    assert 0.05 <= out[0]["confidence"] <= 0.95


def test_rule_even_offer_not_fired_for_group_offer_or_even_groups():
    assert not rules.diagnose({"offer": CAT["grupo_20"], "context": {"odd_share": 0.9}})
    assert not rules.diagnose({"offer": CAT["2x1"], "context": {"odd_share": 0.2}})


def test_rule_promo_after_peak():
    out = rules.diagnose({"offer": CAT["vecinos_10"], "context": {"start_hour": 20, "peak_hour": 18}})
    assert [d["code"] for d in out] == ["PROMO_TRAS_PICO"]
    assert out[0]["evidence"]["delay_h"] == 2


def test_rule_low_ticket_cannibalizes():
    res = {"success": True, "entries_change": 0.4, "ticket_change": -0.3}
    out = rules.diagnose({"offer": CAT["grupo_20"], "context": {}, "result": res})
    assert out[0]["code"] == "TICKET_BAJO_CANIBALIZA"
    assert out[0]["evidence"]["ticket_drop_pct"] == 30


def test_rule_weather_and_competition_and_order():
    ctx = {
        "offer": CAT["2x1"],
        "context": {"odd_share": 0.7, "weather": {"temp_max": 36.2, "rain_mm": 0}, "competitors_100m": 12, "start_hour": 17, "peak_hour": 17},
        "result": {"success": False},
    }
    codes = [d["code"] for d in rules.diagnose(ctx)]
    assert codes == ["OFERTA_PARES_GRUPOS_IMPARES", "CAUSA_EXTERNA_CLIMA", "COMPETENCIA_ALTA"]


def test_rules_order_comes_from_yaml(tmp_path):
    y = tmp_path / "r.yaml"
    y.write_text(
        "rules:\n"
        "  - {code: COMPETENCIA_ALTA, params: {min_competitors: 1}, confidence_base: 0.3, text: 'c {competitors_100m}'}\n"
        "  - {code: PROMO_TRAS_PICO, params: {min_delay_h: 1}, confidence_base: 0.5, text: 'p {delay_h}'}\n",
        encoding="utf-8",
    )
    out = rules.diagnose({"context": {"competitors_100m": 3, "start_hour": 19, "peak_hour": 17}}, rules.load_rules(y))
    assert [d["text"] for d in out] == ["c 3", "p 2"]


# ------------------------------------------------------------------ bandit
def test_bandit_excludes_even_offer_when_odd_groups_dominate():
    r = bandit.recommend({}, "tarde", "grupo_adultos_3_6", odd_share=0.6, rng=random.Random(1))
    assert r["offer"] != "2x1"
    assert any(e["offer"] == "2x1" and "pares" in e["reason"] for e in r["excluded"])


def test_bandit_respects_veto_and_max_discount():
    r = bandit.recommend({}, "tarde", "dos_adultos", odd_share=0.0, vetoed={"grupo_20"}, max_discount=15, rng=random.Random(2))
    assert r["offer"] == "vecinos_10"  # 2x1 (50 %) y grupo_20 (vetada) fuera
    reasons = {e["offer"]: e["reason"] for e in r["excluded"]}
    assert "vetada" in reasons["grupo_20"] and "máximo" in reasons["2x1"]


def test_bandit_learns_from_history():
    arms = {("tarde", "grupo_adultos_3_6", "grupo_20"): Arm(9, 2), ("tarde", "grupo_adultos_3_6", "uno_de_cinco_gratis"): Arm(1, 8)}
    picks = [bandit.recommend(arms, "tarde", "grupo_adultos_3_6", 0.6, rng=random.Random(s))["offer"] for s in range(200)]
    assert picks.count("grupo_20") > 120  # explota la que funciona…
    assert len(set(picks)) > 1  # …sin dejar de explorar


def test_arm_update():
    a = Arm().update(True).update(False).update(True)
    assert (a.alpha, a.beta) == (3, 2) and a.mean == pytest.approx(0.6)


def test_no_eligible_offer():
    r = bandit.recommend({}, "tarde", "solo", 0.0, vetoed={"solo_15", "vecinos_10"})
    assert r["offer"] is None


# ------------------------------------------------------------------ redactor + payload
def _payload():
    obs = [
        {"hour": 18, "segment": "grupo_adultos_3_6", "groups_passing": 40, "groups_entering": 2, "odd_groups": 26},
        {"hour": 18, "segment": "dos_adultos", "groups_passing": 10, "groups_entering": 1, "odd_groups": 0},
    ]
    shop = {"name": "Librería", "street": "FUENCARRAL", "conversion_ref": CONV, "avg_ticket": TICKET, "vetoed_offers": [], "profile": {"max_discount_pct": 20}}
    curve = {h: 100 + (h == 18) * 900 for h in range(10, 21)}
    return build_payload(shop, date(2026, 10, 20), 18, obs, curve, {}, last_offer_in_franja="2x1", rng=random.Random(0))


def test_payload_explains_odd_groups_and_avoids_2x1():
    p = _payload()
    assert p["diagnosis"][0]["code"] == "OFERTA_PARES_GRUPOS_IMPARES"
    assert p["recommendation"]["offer"] != "2x1"
    assert p["opportunity"]["segment"] == "grupo_adultos_3_6"
    assert p["context"]["street_peak_hour"] == 18


def test_template_is_short_and_has_only_payload_numbers():
    p = _payload()
    t = template(p)
    assert len(t.split()) <= 60
    assert validate(t, p) == []


def test_validate_rejects_invented_numbers_and_long_text():
    p = _payload()
    assert validate("Prueba un 35 % de descuento a las 21:00", p)
    assert validate("palabra " * 61, p)


def test_compose_without_key_uses_template():
    text, src = compose(_payload(), api_key="")
    assert src == "template" and text

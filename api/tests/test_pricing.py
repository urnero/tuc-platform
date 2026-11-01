"""Цена (B05): формула, pricing.yaml, API /pricing и /quote."""

from pathlib import Path

import pytest
import yaml
from conftest import REPO_ROOT, box_stl

from app.config import settings
from app.pricing import (
    Pricing,
    PricingError,
    calc_price,
    load_pricing,
    parse_pricing,
    reload_pricing,
)

PRICING_YAML = REPO_ROOT / "config" / "pricing.yaml"

# Простой прайс с круглыми числами — чтобы формулу можно было проверить в уме.
SIMPLE = {
    "currency": "RUB",
    "min_order": 500,
    "margin": 0.5,  # ×1.5
    "k_supports": 1.2,
    "materials": {
        "PLA": {"price_per_g": 10, "tech": "FDM"},
        "PETG": {"price_per_g": 20, "tech": "FDM"},
    },
    "technologies": {"FDM": {"machine_rate": 100}},
    "batch": [{"from": 1, "k": 1.0}, {"from": 10, "k": 0.9}, {"from": 50, "k": 0.8}],
    "postprocess": {"none": 0, "sanding": 150},
    "delivery": {"pickup": 0, "courier_moscow": 400},
}


@pytest.fixture
def simple() -> Pricing:
    return parse_pricing(SIMPLE)


@pytest.fixture
def pricing_file(monkeypatch):
    """API читает настоящий config/pricing.yaml из репозитория."""
    reload_pricing()
    monkeypatch.setattr(settings, "pricing_path", PRICING_YAML)
    yield PRICING_YAML
    reload_pricing()


# --- формула -----------------------------------------------------------------


def test_calc_basic(simple):
    # 50 г × 10 ₽ = 500; 2 ч × 100 ₽ = 200; (500 + 200) × 1.5 = 1050
    q = calc_price(simple, material="PLA", material_g=50, print_time_s=7200)
    assert q.material_cost == 500
    assert q.machine_cost == 200
    assert q.unit_price == 1050
    assert q.print_subtotal == 1050
    assert q.min_order_applied is False
    assert q.postprocess_cost == 0
    assert q.delivery_cost == 0
    assert q.total == 1050
    assert q.tech == "FDM"
    assert q.currency == "RUB"


def test_calc_min_order(simple):
    # 5 г × 10 + 0.1 ч × 100 = 60 × 1.5 = 90 → меньше 500 → 500
    q = calc_price(simple, material="PLA", material_g=5, print_time_s=360)
    assert q.unit_price == 90
    assert q.min_order_applied is True
    assert q.total == 500


def test_calc_min_order_plus_extras(simple):
    # минимальный заказ применяется к печати, доставка и постобработка — сверху
    q = calc_price(
        simple,
        material="PLA",
        material_g=5,
        print_time_s=360,
        postprocess="sanding",
        delivery="courier_moscow",
    )
    assert q.total == 500 + 150 + 400


def test_calc_supports(simple):
    base = calc_price(simple, material="PLA", material_g=50, print_time_s=7200)
    sup = calc_price(simple, material="PLA", material_g=50, print_time_s=7200, supports=True)
    assert sup.k_supports == 1.2
    assert sup.total == round(base.total * 1.2)


@pytest.mark.parametrize(
    "qty, k", [(1, 1.0), (9, 1.0), (10, 0.9), (49, 0.9), (50, 0.8), (500, 0.8)]
)
def test_k_batch_tiers(simple, qty, k):
    assert simple.k_batch(qty) == k


def test_calc_qty_and_batch(simple):
    # 10 штук: 1050 × 0.9 = 945 за штуку, ×10 = 9450; шлифовка 150 × 10
    q = calc_price(
        simple, material="PLA", material_g=50, print_time_s=7200, qty=10, postprocess="sanding"
    )
    assert q.k_batch == 0.9
    assert q.unit_price == 945
    assert q.print_subtotal == 9450
    assert q.postprocess_cost == 1500
    assert q.total == 10950


def test_calc_material_case_insensitive(simple):
    assert calc_price(simple, material="petg", material_g=1, print_time_s=1).material == "PETG"


def test_calc_rounds_to_ruble(simple):
    q = calc_price(simple, material="PLA", material_g=33.33, print_time_s=1234)
    assert isinstance(q.total, int)


def test_calc_rounds_half_up(simple):
    """QA 2026-10-22: 35,1 г × 10 ₽ × 1,5 = 526,5 → 527, а не 526 (round() к чётному)."""
    q = calc_price(simple, material="PLA", material_g=35.1, print_time_s=0)
    assert q.print_subtotal == 526.5
    assert q.total == 527
    q = calc_price(simple, material="PLA", material_g=35.1, print_time_s=0, qty=3)
    assert q.print_subtotal == 1579.5 and q.total == 1580


@pytest.mark.parametrize(
    "kwargs, text",
    [
        ({"material": "WOOD"}, "Материал"),
        ({"postprocess": "paint"}, "Постобработка"),
        ({"delivery": "mars"}, "Доставка"),
        ({"qty": 0}, "Тираж"),
        ({"material_g": -1}, "отрицательн"),
    ],
)
def test_calc_bad_input(simple, kwargs, text):
    args = {"material": "PLA", "material_g": 10, "print_time_s": 600, **kwargs}
    with pytest.raises(PricingError, match=text):
        calc_price(simple, **args)


# --- pricing.yaml ------------------------------------------------------------


def test_repo_pricing_yaml_is_valid():
    pricing = parse_pricing(yaml.safe_load(PRICING_YAML.read_text("utf-8")))
    assert set(pricing.materials) >= {"PLA", "PETG", "ABS"}
    assert pricing.min_order > 0
    assert "pickup" in pricing.delivery
    assert "none" in pricing.postprocess


def test_repo_pricing_numbers_are_sane():
    """B45: оценка по рынку — числа не потеряли смысл (опечатка 23 вместо 2.3 и т. п.)."""
    from app.telegram import DELIVERY_LABELS, POSTPROCESS_LABELS

    pricing = parse_pricing(yaml.safe_load(PRICING_YAML.read_text("utf-8")))
    for name, m in pricing.materials.items():
        assert 0.5 <= m["price_per_g"] <= 50, name
    assert 0 < pricing.margin < 2
    assert pricing.k_supports >= 1
    ks = [t["k"] for t in pricing.batch]
    assert ks == sorted(ks, reverse=True) and all(0 < k <= 1 for k in ks), "скидка растёт с тиражом"
    # у каждого варианта есть подпись в карточке Telegram (на сайте — web/lib/pricing.ts)
    assert set(pricing.delivery) <= set(DELIVERY_LABELS)
    assert set(pricing.postprocess) <= set(POSTPROCESS_LABELS)
    # PLA, деталь 50 г / 3 ч: цена за грамм в коридоре рынка Москвы (DECISIONS 2026-10-29)
    q = calc_price(pricing, material="PLA", material_g=50, print_time_s=3 * 3600)
    assert 5 <= q.total / 50 <= 15


def test_repo_pricing_matches_slicer_materials():
    """Материалы в pricing.yaml = профили в profiles/filament/, иначе цену не посчитать."""
    from app import materials

    pricing = parse_pricing(yaml.safe_load(PRICING_YAML.read_text("utf-8")))
    assert set(materials.sliceable()) <= set(pricing.materials)


def test_parse_pricing_errors():
    with pytest.raises(PricingError, match="нет ключа"):
        parse_pricing({**SIMPLE, "materials": {"PLA": {"tech": "FDM"}}})
    with pytest.raises(PricingError, match="не описана"):
        parse_pricing({**SIMPLE, "materials": {"PLA": {"price_per_g": 1, "tech": "SLA"}}})
    with pytest.raises(PricingError, match="числом"):
        parse_pricing({**SIMPLE, "min_order": "много"})
    with pytest.raises(PricingError, match="from: 1"):
        parse_pricing({**SIMPLE, "batch": [{"from": 10, "k": 0.9}]})
    with pytest.raises(PricingError):
        parse_pricing(["не", "словарь"])


def test_load_pricing_missing_file(tmp_path):
    with pytest.raises(PricingError, match="Нет файла"):
        load_pricing(tmp_path / "nope.yaml")


def test_load_pricing_cached(tmp_path: Path):
    path = tmp_path / "p.yaml"
    path.write_text(yaml.safe_dump(SIMPLE), "utf-8")
    first = load_pricing(path)
    path.write_text(yaml.safe_dump({**SIMPLE, "min_order": 999}), "utf-8")
    assert load_pricing(path).min_order == first.min_order  # кэш
    reload_pricing()
    assert load_pricing(path).min_order == 999


# --- API ---------------------------------------------------------------------


def test_api_pricing(client, pricing_file):
    r = client.get("/api/v1/pricing")
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "RUB"
    assert "PLA" in body["materials"]
    assert body["batch"][0]["from"] == 1
    assert "courier_moscow" in body["delivery"]


def _upload(client) -> str:
    r = client.post("/api/v1/uploads", files={"file": ("box.stl", box_stl(), "model/stl")})
    assert r.status_code == 201
    return r.json()["id"]


def test_api_quote_requires_slice(client, pricing_file, fake_slicer):
    upload_id = _upload(client)
    r = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA"})
    assert r.status_code == 409
    assert "Сначала" in r.json()["detail"]


def test_api_quote_flow(client, pricing_file, fake_slicer):
    upload_id = _upload(client)
    s = client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    assert s.status_code == 202 and s.json()["status"] == "done"
    grams = s.json()["result"]["filament_g"]

    r = client.post(
        f"/api/v1/uploads/{upload_id}/quote",
        json={"material": "pla", "qty": 2, "delivery": "courier_moscow"},
    )
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["material"] == "PLA"
    assert q["material_g"] == grams
    assert q["qty"] == 2
    assert q["delivery_cost"] == 450
    assert q["total"] >= 450 + q["min_order"]
    assert q["upload_id"] == upload_id
    assert q["original_name"] == "box.stl"

    # сохранённый расчёт читается по id
    g = client.get(f"/api/v1/quotes/{q['id']}")
    assert g.status_code == 200
    assert g.json() == q

    # меняем тираж — новый расчёт, слайсить заново не нужно
    r2 = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA", "qty": 10})
    assert r2.status_code == 201
    assert r2.json()["k_batch"] < 1
    assert r2.json()["id"] != q["id"]


def test_api_quote_bad_choices(client, pricing_file, fake_slicer):
    upload_id = _upload(client)
    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    r = client.post(
        f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA", "delivery": "mars"}
    )
    assert r.status_code == 422
    r = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "WOOD"})
    assert r.status_code == 422
    r = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA", "qty": 0})
    assert r.status_code == 422


def test_api_quote_not_found(client, pricing_file):
    assert client.get("/api/v1/quotes/../../etc/passwd").status_code in (404, 422)
    assert client.get("/api/v1/quotes/" + "0" * 32 + "-abcdef").status_code == 404
    assert client.post("/api/v1/uploads/" + "0" * 32 + "/quote", json={}).status_code == 404


def test_api_quote_units_change_invalidates(client, pricing_file, fake_slicer):
    """[ДЕНЬГИ] после «мм → дюймы» старый расчёт цены удалён (заказ по нему невозможен),
    а новый расчёт цены требует расчёта печати для новых единиц.
    Коробка 2×3×4: в дюймах 51×76×102 мм — влезает в принтер."""
    r = client.post("/api/v1/uploads", files={"file": ("b.stl", box_stl(2, 3, 4), "model/stl")})
    upload_id = r.json()["id"]
    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    q = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA"}).json()
    assert q["units"] == "mm"

    assert client.patch(f"/api/v1/uploads/{upload_id}", json={"units": "inch"}).status_code == 200
    assert client.get(f"/api/v1/quotes/{q['id']}").status_code == 404
    r = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA"})
    assert r.status_code == 409  # расчёт печати для дюймов ещё не делали
    assert "Статус расчёта: none" in r.json()["detail"]

    client.post(f"/api/v1/uploads/{upload_id}/slice", json={"material": "PLA"})
    q2 = client.post(f"/api/v1/uploads/{upload_id}/quote", json={"material": "PLA"}).json()
    assert q2["units"] == "inch"
    assert q2["material_g"] > q["material_g"]
    assert q2["total"] >= q["total"]


# --- ориентир до слайсера -----------------------------------------------------------------

def test_estimate_print_cube_20mm():
    from app.pricing import estimate_print

    # калибровочный куб 20 мм: объём 8 см³, площадь 24 см² → оболочка 2,4 + 15 % от 5,6
    grams, seconds = estimate_print(8.0, 24.0)
    assert grams == round((2.4 + 5.6 * 0.15) * 1.24, 1)
    assert 15 * 60 < seconds < 30 * 60  # реальный слайсер даёт ~20–25 минут


def test_estimate_print_thin_part_shell_not_bigger_than_volume():
    from app.pricing import estimate_print

    grams, _ = estimate_print(1.0, 500.0)  # тонкая пластина: «оболочка» больше объёма
    assert grams == round(1.0 * 1.24, 1)
    assert estimate_print(-1, -1) == (0.0, 0)


def test_estimate_price_uses_calc_price():
    from app.pricing import calc_price, estimate_price, estimate_print

    p = parse_pricing(SIMPLE)
    grams, seconds = estimate_print(500.0, 600.0)
    q = estimate_price(p, material="PLA", volume_cm3=500.0, surface_cm2=600.0)
    assert q.total == calc_price(p, material="PLA", material_g=grams, print_time_s=seconds).total

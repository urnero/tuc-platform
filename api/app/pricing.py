"""Расчёт цены печати (B05). ВСЕ денежные вычисления — здесь, в одной функции `calc_price`.

Параметры берутся из `config/pricing.yaml` (путь — PRICING_PATH в .env). Формула из docs/SPEC.md:

    price = max(min_order,
                (material_g × price_per_g[material] + print_h × machine_rate[tech])
                × k_supports × k_batch(qty) × (1 + margin))
            + postprocess + delivery

Как мы её читаем (см. docs/DECISIONS.md от 2026-10-19):
- material_g и print_h — на ОДНО изделие (из слайсера), умножаем на qty;
- min_order сравниваем с суммой за печать всего тиража (без постобработки и доставки);
- postprocess — за каждое изделие, delivery — один раз за заказ;
- итог округляем до рубля.

Пример:
    >>> p = load_pricing()
    >>> calc_price(p, material="PLA", material_g=50, print_time_s=7200, qty=1).total
    594   # (50 г × 4 ₽ + 2 ч × 120 ₽) × 1.35 = 594 ₽; самовывоз, без постобработки
"""

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import settings


class PricingError(ValueError):
    """Неверный выбор клиента (материал, постобработка, доставка) или битый pricing.yaml."""


@dataclass(frozen=True)
class Pricing:
    """Прайс, прочитанный из pricing.yaml. Неизменяемый — один на процесс."""

    currency: str
    min_order: float
    margin: float
    k_supports: float
    materials: dict[str, dict]  # PLA → {price_per_g, tech}
    technologies: dict[str, dict]  # FDM → {machine_rate}
    batch: list[dict]  # [{from, k}, ...] по возрастанию from
    postprocess: dict[str, float]  # none → 0, sanding → 150
    delivery: dict[str, float]  # pickup → 0, courier_moscow → 400

    def k_batch(self, qty: int) -> float:
        """Коэффициент тиража: берём ступень с наибольшим `from`, не превышающим qty."""
        k = 1.0
        for tier in self.batch:
            if qty >= int(tier["from"]):
                k = float(tier["k"])
        return k

    def public(self) -> dict:
        """То, что отдаём на форму: списки вариантов и ставки. Секретов тут нет."""
        return asdict(self)


def _as_float(value, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise PricingError(f"pricing.yaml: {name} должно быть числом, а не {value!r}") from e


def parse_pricing(raw: dict) -> Pricing:
    """Проверяет содержимое yaml и собирает Pricing. Ошибка в файле → PricingError с подсказкой."""
    if not isinstance(raw, dict):
        raise PricingError("pricing.yaml: ожидался словарь с ключами min_order, materials, ...")
    try:
        materials = {
            str(name).upper(): {
                "price_per_g": _as_float(m["price_per_g"], f"materials.{name}.price_per_g"),
                "tech": str(m["tech"]).upper(),
            }
            for name, m in raw["materials"].items()
        }
        technologies = {
            str(name).upper(): {
                "machine_rate": _as_float(t["machine_rate"], f"technologies.{name}.machine_rate")
            }
            for name, t in raw["technologies"].items()
        }
        batch = sorted(
            ({"from": int(t["from"]), "k": _as_float(t["k"], "batch.k")} for t in raw["batch"]),
            key=lambda t: t["from"],
        )
        pricing = Pricing(
            currency=str(raw.get("currency", "RUB")),
            min_order=_as_float(raw["min_order"], "min_order"),
            margin=_as_float(raw["margin"], "margin"),
            k_supports=_as_float(raw["k_supports"], "k_supports"),
            materials=materials,
            technologies=technologies,
            batch=batch,
            postprocess={
                str(k): _as_float(v, f"postprocess.{k}") for k, v in raw["postprocess"].items()
            },
            delivery={str(k): _as_float(v, f"delivery.{k}") for k, v in raw["delivery"].items()},
        )
    except KeyError as e:
        raise PricingError(f"pricing.yaml: нет ключа {e}") from e
    for name, m in pricing.materials.items():
        if m["tech"] not in pricing.technologies:
            raise PricingError(
                f"pricing.yaml: у материала {name} технология {m['tech']} не описана"
            )
    if not pricing.batch or pricing.batch[0]["from"] > 1:
        raise PricingError("pricing.yaml: в batch нужна ступень с from: 1")
    return pricing


@lru_cache(maxsize=4)
def _load_cached(path: str) -> Pricing:
    raw = yaml.safe_load(Path(path).read_text("utf-8"))
    return parse_pricing(raw)


def load_pricing(path: Path | None = None) -> Pricing:
    """Читает pricing.yaml один раз на процесс (кэш по пути). Сменил файл — перезапусти API."""
    path = path or settings.pricing_path
    if not Path(path).is_file():
        raise PricingError(f"Нет файла с ценами: {path}")
    return _load_cached(str(Path(path).resolve()))


def reload_pricing() -> None:
    """Сброс кэша — для тестов и для будущей админки."""
    _load_cached.cache_clear()


@dataclass(frozen=True)
class Quote:
    """Результат расчёта. Все суммы в рублях; `total` — то, что платит клиент."""

    currency: str
    material: str
    tech: str
    supports: bool
    qty: int
    postprocess: str
    delivery: str
    # исходные данные на одно изделие
    material_g: float
    print_time_s: int
    # ставки, по которым считали (чтобы владелец видел, откуда цифра)
    price_per_g: float
    machine_rate: float
    k_supports: float
    k_batch: float
    margin: float
    min_order: float
    # разложение суммы
    material_cost: float  # пластик на весь тираж, до наценки
    machine_cost: float  # работа принтера на весь тираж, до наценки
    unit_price: float  # цена одного изделия с коэффициентами и наценкой
    print_subtotal: float  # unit_price × qty
    min_order_applied: bool  # печать вышла дешевле минимального заказа
    postprocess_cost: float  # постобработка на весь тираж
    delivery_cost: float
    total: int

    def to_dict(self) -> dict:
        return asdict(self)


def calc_price(
    pricing: Pricing,
    *,
    material: str,
    material_g: float,
    print_time_s: int,
    supports: bool = False,
    qty: int = 1,
    postprocess: str = "none",
    delivery: str = "pickup",
) -> Quote:
    """Считает цену по формуле из SPEC. Единственное место, где умножаются деньги."""
    material = material.upper()
    if material not in pricing.materials:
        raise PricingError(f"Материал: {', '.join(pricing.materials)}.")
    if postprocess not in pricing.postprocess:
        raise PricingError(f"Постобработка: {', '.join(pricing.postprocess)}.")
    if delivery not in pricing.delivery:
        raise PricingError(f"Доставка: {', '.join(pricing.delivery)}.")
    if qty < 1:
        raise PricingError("Тираж — от 1 штуки.")
    if material_g < 0 or print_time_s < 0:
        raise PricingError("Граммы и время печати не могут быть отрицательными.")

    tech = pricing.materials[material]["tech"]
    price_per_g = pricing.materials[material]["price_per_g"]
    machine_rate = pricing.technologies[tech]["machine_rate"]
    k_supports = pricing.k_supports if supports else 1.0
    k_batch = pricing.k_batch(qty)
    print_h = print_time_s / 3600.0

    # одно изделие
    unit_base = material_g * price_per_g + print_h * machine_rate
    unit_price = unit_base * k_supports * k_batch * (1 + pricing.margin)

    print_subtotal = unit_price * qty
    min_order_applied = print_subtotal < pricing.min_order
    print_part = max(pricing.min_order, print_subtotal)

    postprocess_cost = pricing.postprocess[postprocess] * qty
    delivery_cost = pricing.delivery[delivery]
    total = int(round(print_part + postprocess_cost + delivery_cost))

    r2 = lambda v: round(v, 2)  # noqa: E731 — короткая запись для сумм в ответе
    return Quote(
        currency=pricing.currency,
        material=material,
        tech=tech,
        supports=supports,
        qty=qty,
        postprocess=postprocess,
        delivery=delivery,
        material_g=material_g,
        print_time_s=print_time_s,
        price_per_g=price_per_g,
        machine_rate=machine_rate,
        k_supports=k_supports,
        k_batch=k_batch,
        margin=pricing.margin,
        min_order=pricing.min_order,
        material_cost=r2(material_g * price_per_g * qty),
        machine_cost=r2(print_h * machine_rate * qty),
        unit_price=r2(unit_price),
        print_subtotal=r2(print_subtotal),
        min_order_applied=min_order_applied,
        postprocess_cost=r2(postprocess_cost),
        delivery_cost=r2(delivery_cost),
        total=total,
    )

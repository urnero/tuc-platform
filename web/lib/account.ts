/**
 * Кабинет клиента (B32): типы ответов /api/v1/account, ссылка «Повторить заказ»,
 * разбор параметров повтора на странице модели.
 *
 * Вход: POST /api/v1/account/login {email} → код письмом → POST /login/confirm {email, code}
 * → cookie. Дальше GET /api/v1/account (кто вошёл) и GET /api/v1/account/orders (история).
 */

import type { Order } from "./order";

/** GET /api/v1/account. `contacts` — из последнего заказа, подставляются в форму нового. */
export type Account = {
  email: string;
  orders_count: number;
  contacts: { name: string; phone: string; address: string } | null;
};

/** Строка истории: заказ + можно ли повторить (файл модели ещё не удалён). */
export type AccountOrder = Order & { can_repeat: boolean };

/** Шаги экрана входа: ввод адреса → ввод кода → вошли. */
export type LoginStep = "email" | "code";

/** Те же параметры расчёта, что были в заказе: с ними открывается страница модели. */
export type Preset = {
  material: string;
  supports: boolean;
  qty: number;
  postprocess: string;
  delivery: string;
};

/** Ссылка «Повторить»: страница модели с параметрами прошлого заказа в адресе.
 *  Цена считается заново по текущему прайсу — старая не повторяется. */
export function repeatHref(order: Pick<Order, "upload_id" | "material" | "supports" | "qty" | "postprocess" | "delivery">): string {
  const q = new URLSearchParams({
    material: order.material,
    supports: order.supports ? "1" : "0",
    qty: String(order.qty),
    postprocess: order.postprocess,
    delivery: order.delivery,
  });
  return `/upload/${order.upload_id}?${q.toString()}`;
}

/** Параметры повтора из адреса страницы модели; null — пришли не из кабинета. */
export function parsePreset(search: string): Preset | null {
  const q = new URLSearchParams(search);
  const material = q.get("material");
  if (!material) return null;
  const qty = Number.parseInt(q.get("qty") ?? "1", 10);
  return {
    material,
    supports: q.get("supports") === "1",
    qty: Number.isFinite(qty) && qty >= 1 ? Math.min(qty, 1000) : 1,
    postprocess: q.get("postprocess") || "none",
    delivery: q.get("delivery") || "pickup",
  };
}

/** Код из письма: оставляем только цифры (клиент может вставить с пробелами). */
export function cleanCode(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, 6);
}

/** Текст ошибки для экрана входа по ответу API. */
export function loginError(status: number, detail?: unknown): string {
  if (typeof detail === "string" && detail) return detail;
  if (status === 429) return "Слишком много попыток. Подождите минуту.";
  if (status === 503) return "Вход в кабинет пока недоступен. Напишите нам — поможем по заказу.";
  return `Ошибка ${status}.`;
}

/** Заголовок списка: «3 заказа», «1 заказ», «5 заказов». */
export function ordersCountLabel(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const word =
    mod10 === 1 && mod100 !== 11 ? "заказ" : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "заказа" : "заказов";
  return `${n} ${word}`;
}

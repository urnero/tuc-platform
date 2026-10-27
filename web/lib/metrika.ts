/**
 * Яндекс.Метрика (B51). Счётчик создаёт владелец; его номер — в NEXT_PUBLIC_YM_ID.
 * Нет номера (или он не число) — всё молча выключено: скрипт не грузится, цели не шлются.
 * Цели воронки: upload, quote, order, paid — названия совпадают с `events.name` (ANALYTICS.md).
 */

export type Goal = "upload" | "quote" | "order" | "paid";

/** Номер счётчика или null, если не задан / задан криво (только цифры). */
export function ymId(raw: string | undefined = process.env.NEXT_PUBLIC_YM_ID): string | null {
  const v = (raw ?? "").trim();
  return /^\d{4,12}$/.test(v) ? v : null;
}

/** Код загрузки счётчика (стандартный фрагмент Метрики, webvisor выключен). */
export function ymSnippet(id: string): string {
  return (
    `(function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};` +
    `m[i].l=1*new Date();k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)})` +
    `(window,document,"script","https://mc.yandex.ru/metrika/tag.js","ym");` +
    `ym(${id},"init",{clickmap:true,trackLinks:true,accurateTrackBounce:true});`
  );
}

/**
 * Отправить цель. `once` — ключ, чтобы одну и ту же цель за сессию вкладки слать один раз
 * (например, «paid» для заказа, страницу которого открыли дважды).
 */
export function reachGoal(goal: Goal, once?: string): void {
  const id = ymId();
  if (!id || typeof window === "undefined") return;
  const w = window as unknown as { ym?: (id: number, action: string, goal: string) => void };
  if (typeof w.ym !== "function") return;
  if (once) {
    try {
      const key = `ym:${goal}:${once}`;
      if (window.sessionStorage.getItem(key)) return;
      window.sessionStorage.setItem(key, "1");
    } catch {
      /* хранилище недоступно — шлём как есть */
    }
  }
  w.ym(Number(id), "reachGoal", goal);
}

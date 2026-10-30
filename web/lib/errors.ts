/**
 * Ошибки человеческим языком (B42).
 *
 * Сервер в большинстве случаев сам пишет понятный текст в `detail` — его и показываем.
 * Здесь подменяем то, что клиенту ничего не скажет: «Failed to fetch», «Ошибка 502»,
 * список ошибок проверки FastAPI (detail — массив), технические сообщения слайсера.
 */

/** Нет связи с сервером (fetch упал до ответа). */
export const NETWORK_ERROR = "Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.";

/** Сервер недоступен / обновляется (5xx без понятного текста). */
export const SERVER_BUSY = "Сервер сейчас недоступен — возможно, обновляется. Попробуйте через минуту.";

/**
 * Текст ошибки по ответу API: статус + поле `detail` из JSON (если было).
 * Понятный текст сервера (строка по-русски) оставляем как есть.
 */
export function apiErrorText(status: number, detail?: unknown): string {
  const text = typeof detail === "string" ? detail.trim() : "";
  // Строка с кириллицей — сервер уже объяснил по-человечески (кроме технических слайсера).
  if (text && /[а-яё]/i.test(text) && !isTechnical(text)) return text;
  if (status === 0) return NETWORK_ERROR;
  if (status === 404) return "Не нашли то, что вы ищете: возможно, ссылка устарела. Загрузите модель заново.";
  if (status === 410) return "Расчёт устарел. Вернитесь к модели и посчитайте цену ещё раз.";
  if (status === 413) return "Файл слишком большой: максимум 100 МБ.";
  if (status === 422) return "Проверьте введённые данные — что-то заполнено не так.";
  if (status === 429) return "Слишком много запросов подряд. Подождите минуту и попробуйте снова.";
  if (status >= 500) return SERVER_BUSY;
  return "Что-то пошло не так. Обновите страницу и попробуйте ещё раз.";
}

/** Читает `detail` из ответа (если тело не JSON — пусто) и возвращает понятный текст. */
export async function responseErrorText(r: Response): Promise<string> {
  const body = (await r.json().catch(() => ({}))) as { detail?: unknown };
  return apiErrorText(r.status, body.detail);
}

/** Ошибка из catch: сетевой сбой fetch → «нет связи», иначе текст как есть. */
export function caughtErrorText(e: unknown): string {
  if (e instanceof TypeError) return NETWORK_ERROR; // fetch бросает TypeError, когда ответа нет
  return e instanceof Error && e.message ? e.message : SERVER_BUSY;
}

const TECHNICAL = [/слайсер/i, /g-code/i, /prusaslicer/i, /профил/i, /traceback/i, /PRUSA_SLICER_BIN/];

function isTechnical(text: string): boolean {
  return TECHNICAL.some((re) => re.test(text));
}

/**
 * Ошибка расчёта печати (поле `error` записи слайсинга) → что сказать клиенту и что делать.
 * Исходный текст остаётся в логах сервера и в админке — клиенту он не нужен.
 */
export function sliceErrorText(raw: string | null | undefined): string {
  const text = (raw ?? "").trim();
  if (/не уложился|timeout|таймаут/i.test(text)) {
    return "Модель слишком сложная для автоматического расчёта. Напишите нам — посчитаем вручную.";
  }
  if (/не найден prusaslicer|нет профиля/i.test(text)) {
    return "Расчёт временно не работает на нашей стороне. Мы уже знаем — попробуйте позже или напишите нам.";
  }
  if (/материал:/i.test(text)) return "Этот материал сейчас недоступен — выберите другой.";
  if (/единицы:/i.test(text)) return "Не поняли единицы модели — выберите миллиметры или дюймы и пересчитайте.";
  if (text && /[а-яё]/i.test(text) && !isTechnical(text)) return text;
  return (
    "Не получилось нарезать модель на слои. Частые причины: модель больше области печати, " +
    "в сетке дыры или выбраны не те единицы (мм/дюймы). Попробуйте включить поддержки или напишите нам — посмотрим вручную."
  );
}

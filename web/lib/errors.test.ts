import { describe, expect, it } from "vitest";
import { apiErrorText, caughtErrorText, NETWORK_ERROR, SERVER_BUSY, sliceErrorText } from "./errors";

describe("apiErrorText", () => {
  it("понятный текст сервера показываем как есть", () => {
    expect(apiErrorText(429, "Слишком много загрузок подряд. Подождите минуту и попробуйте снова.")).toMatch(/^Слишком много загрузок/);
  });
  it("502 без текста — сервер недоступен", () => {
    expect(apiErrorText(502)).toBe(SERVER_BUSY);
  });
  it("422 со списком ошибок FastAPI — общий текст про данные", () => {
    expect(apiErrorText(422, [{ loc: ["body", "phone"], msg: "field required" }])).toMatch(/Проверьте введённые данные/);
  });
  it("английский текст не показываем", () => {
    expect(apiErrorText(500, "Internal Server Error")).toBe(SERVER_BUSY);
  });
  it("технический текст слайсера заменяем", () => {
    expect(apiErrorText(422, "Нет профиля слайсера: profiles/x.ini")).not.toMatch(/профил/);
  });
  it("410 — расчёт устарел", () => {
    expect(apiErrorText(410)).toMatch(/устарел/);
  });
});

describe("caughtErrorText", () => {
  it("TypeError от fetch — нет связи", () => {
    expect(caughtErrorText(new TypeError("Failed to fetch"))).toBe(NETWORK_ERROR);
  });
  it("обычная ошибка — её текст", () => {
    expect(caughtErrorText(new Error("Расчёт не найден."))).toBe("Расчёт не найден.");
  });
});

describe("sliceErrorText", () => {
  it("таймаут — посчитаем вручную", () => {
    expect(sliceErrorText("Слайсер не уложился в 300 с.")).toMatch(/вручную/);
  });
  it("падение слайсера — частые причины без технических деталей", () => {
    const t = sliceErrorText("Слайсер завершился с ошибкой: Objects could not fit on the bed");
    expect(t).toMatch(/области печати/);
    expect(t).not.toMatch(/bed/);
  });
  it("нет PrusaSlicer — проблема на нашей стороне", () => {
    expect(sliceErrorText("Не найден PrusaSlicer: prusa-slicer. Проверь PRUSA_SLICER_BIN")).toMatch(/на нашей стороне/);
  });
  it("пусто — общий текст", () => {
    expect(sliceErrorText(null)).toMatch(/Не получилось/);
  });
});

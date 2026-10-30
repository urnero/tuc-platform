import { describe, expect, it } from "vitest";
import { formatDuration, formatGrams, SUPPORTS_DEFAULT, supportsNote } from "./slice";

describe("formatDuration", () => {
  it("часы и минуты", () => {
    expect(formatDuration(3723)).toBe("1 ч 3 мин");
  });
  it("меньше минуты — 1 мин", () => {
    expect(formatDuration(30)).toBe("1 мин");
  });
  it("только минуты", () => {
    expect(formatDuration(45 * 60)).toBe("45 мин");
  });
  it("ровно часы", () => {
    expect(formatDuration(2 * 3600)).toBe("2 ч");
  });
  it("59 мин 50 с округляет до следующего часа", () => {
    expect(formatDuration(3600 + 59 * 60 + 50)).toBe("2 ч");
  });
  it("дни", () => {
    expect(formatDuration(2 * 86400 + 3 * 3600 + 100)).toBe("2 д 3 ч");
  });
});

describe("formatGrams", () => {
  it("меньше 10 г — с десятыми", () => {
    expect(formatGrams(8.89)).toBe("8,9 г");
  });
  it("больше 10 г — целые", () => {
    expect(formatGrams(123.4)).toBe("123 г");
  });
});

import { formatElapsed, MATERIAL_HINTS, sliceSteps } from "./slice";

describe("sliceSteps", () => {
  const states = (s: ReturnType<typeof sliceSteps>) => s.map((x) => x.state).join(",");
  it("в очереди", () => {
    expect(states(sliceSteps("queued", false))).toBe("done,active,todo,todo");
  });
  it("нарезка", () => {
    expect(states(sliceSteps("running", false))).toBe("done,done,active,todo");
  });
  it("печать посчитана, цены ещё нет", () => {
    expect(states(sliceSteps("done", false))).toBe("done,done,done,active");
  });
  it("всё готово", () => {
    expect(states(sliceSteps("done", true))).toBe("done,done,done,done");
  });
  it("ошибка — остановились на нарезке", () => {
    expect(states(sliceSteps("error", false))).toBe("done,done,active,todo");
  });
});

describe("formatElapsed / MATERIAL_HINTS", () => {
  it("секунды и минуты", () => {
    expect(formatElapsed(7.9)).toBe("7 с");
    expect(formatElapsed(65)).toBe("1 мин 5 с");
    expect(formatElapsed(120)).toBe("2 мин");
  });
  it("подсказки есть для материалов прайса", () => {
    for (const m of ["PLA", "PETG", "ABS"]) expect(MATERIAL_HINTS[m]).toBeTruthy();
  });
});

describe("поддержки — решит мастерская", () => {
  it("по умолчанию включены (авто по нависаниям)", () => {
    expect(SUPPORTS_DEFAULT).toBe(true);
  });
  it("выключены клиентом — ничего не пишем", () => {
    expect(supportsNote({ supports: false })).toBe("");
  });
  it("слайсер поставил поддержки", () => {
    expect(supportsNote({ supports: true, supports_used: true })).toBe(", с поддержками");
  });
  it("нависаний нет — поддержки не нужны", () => {
    expect(supportsNote({ supports: true, supports_used: false })).toBe(", поддержки не нужны");
  });
  it("старый расчёт без поля — как раньше", () => {
    expect(supportsNote({ supports: true })).toBe(", с поддержками");
  });
});

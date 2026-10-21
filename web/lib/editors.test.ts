import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type Editor,
  type EditorParam,
  defaultValues,
  fmt,
  loadEditor,
  parseNumber,
  toRequestParams,
  validateValue,
  validateValues,
} from "./editors";

const param = (extra: Partial<EditorParam> & { name: string }): EditorParam => ({
  label: extra.name,
  type: "number",
  default: 0,
  hint: "",
  unit: "",
  min: null,
  max: null,
  step: null,
  integer: false,
  options: [],
  maxlen: 40,
  ...extra,
});

const editor: Editor = {
  slug: "spacer",
  title: "Втулка",
  text: "",
  material: "PETG",
  scad: "model.scad",
  order: 10,
  scad_ready: true,
  params: [
    param({ name: "outer_d", label: "Внешний диаметр", unit: "мм", min: 4, max: 200, step: 0.5, default: 20 }),
    param({ name: "inner_d", label: "Отверстие", unit: "мм", min: 1, max: 195, step: 0.5, default: 8.5 }),
    param({ name: "count", label: "Штук", integer: true, min: 1, max: 10, default: 1 }),
    param({ name: "shape", label: "Форма", type: "choice", default: "round", options: [{ value: "round", label: "Круглая" }, { value: "hex", label: "Шестигранник" }] }),
    param({ name: "chamfer", label: "Фаска", type: "bool", default: true }),
    param({ name: "text", label: "Надпись", type: "text", default: "", maxlen: 5 }),
  ],
  checks: [
    { rule: "inner_d < outer_d", message: "Отверстие должно быть меньше внешнего диаметра." },
    { rule: "count >= 1", message: "Хотя бы одна." },
  ],
};

describe("defaultValues", () => {
  it("числа и текст — строками, галочки — boolean", () => {
    expect(defaultValues(editor)).toEqual({
      outer_d: "20",
      inner_d: "8.5",
      count: "1",
      shape: "round",
      chamfer: true,
      text: "",
    });
  });
});

describe("parseNumber / fmt", () => {
  it("запятая как разделитель, пусто — NaN", () => {
    expect(parseNumber("12,5")).toBe(12.5);
    expect(parseNumber(" 7 ")).toBe(7);
    expect(parseNumber("")).toBeNaN();
    expect(parseNumber("abc")).toBeNaN();
  });
  it("fmt убирает хвосты и ставит запятую", () => {
    expect(fmt(20)).toBe("20");
    expect(fmt(8.5)).toBe("8,5");
    expect(fmt(0.1 + 0.2)).toBe("0,3");
  });
});

describe("validateValue", () => {
  const [outer, , count, shape, chamfer, text] = editor.params;
  it("числа: границы с единицей, целые", () => {
    expect(validateValue(outer, "20")).toBeNull();
    expect(validateValue(outer, "3,5")).toBe("Не меньше 4 мм.");
    expect(validateValue(outer, "201")).toBe("Не больше 200 мм.");
    expect(validateValue(outer, "")).toBe("Нужно число.");
    expect(validateValue(outer, "x")).toBe("Нужно число.");
    expect(validateValue(count, "2.5")).toBe("Нужно целое число.");
    expect(validateValue(count, "11")).toBe("Не больше 10.");
  });
  it("выбор, галочка, текст", () => {
    expect(validateValue(shape, "hex")).toBeNull();
    expect(validateValue(shape, "oval")).toBe("Выберите один из вариантов.");
    expect(validateValue(chamfer, false)).toBeNull();
    expect(validateValue(chamfer, "yes")).toBe("Нужно да или нет.");
    expect(validateValue(text, "abcde")).toBeNull();
    expect(validateValue(text, "abcdef")).toBe("Не длиннее 5 символов.");
    expect(validateValue(text, "a\nb")).toBe("Текст без переносов строк и служебных символов.");
  });
});

describe("validateValues", () => {
  it("умолчания проходят; правило между параметрами — на левом поле", () => {
    expect(validateValues(editor, defaultValues(editor))).toEqual({});
    const values = { ...defaultValues(editor), inner_d: "25" };
    expect(validateValues(editor, values)).toEqual({ inner_d: "Отверстие должно быть меньше внешнего диаметра." });
  });
  it("пока есть ошибки по полям, правила не проверяем", () => {
    const values = { ...defaultValues(editor), outer_d: "x", inner_d: "25" };
    expect(validateValues(editor, values)).toEqual({ outer_d: "Нужно число." });
  });
  it("правило с числом справа", () => {
    const values = { ...defaultValues(editor), count: "0" };
    expect(validateValues(editor, values)).toEqual({ count: "Не меньше 1." });
  });
});

describe("toRequestParams", () => {
  it("числа числами, текст обрезан, галочка boolean", () => {
    const values = { ...defaultValues(editor), outer_d: "30,5", text: " hi " };
    expect(toRequestParams(editor, values)).toEqual({
      outer_d: 30.5,
      inner_d: 8.5,
      count: 1,
      shape: "round",
      chamfer: true,
      text: "hi",
    });
  });
});

describe("loadEditor", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("плохой slug — null без запроса; 404 — null", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404 });
    vi.stubGlobal("fetch", fetchMock);
    expect(await loadEditor("../etc")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(await loadEditor("spacer")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ошибка сети — null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    expect(await loadEditor("spacer")).toBeNull();
  });
});

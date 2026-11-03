import { describe, expect, it } from "vitest";
import { makePlacement } from "./math";
import {
  activeDraft,
  createEditorStore,
  INITIAL_STATE,
  editAgainHref,
  overlayFromParams,
  overlaysFromParams,
  overlaysProblem,
  MAX_OVERLAYS,
  toEmbossBody,
  toolFromParam,
  overlayProblem,
  reduce,
  selectedOverlay,
  toEmbossParams,
  type Action,
} from "./store";

const top = makePlacement([0, 0, 10], [0, 0, 1], [0, 1, 0]);
const side = makePlacement([5, 0, 3], [1, 0, 0], [0, 0, 1]);

function run(actions: Action[]) {
  return actions.reduce(reduce, INITIAL_STATE);
}

describe("редьюсер редактора", () => {
  it("наведение показывает плашку, клик ставит наложение из черновика и выбирает его", () => {
    const s1 = reduce(INITIAL_STATE, { type: "hover", placement: top });
    expect(s1.hover).toBe(top);
    const s2 = reduce(s1, { type: "draft", patch: { text: "Маше", size_mm: 12 } });
    const s3 = reduce(s2, { type: "place", placement: top });
    expect(s3.overlays).toHaveLength(1);
    expect(s3.overlays[0]).toMatchObject({ kind: "text", text: "Маше", size_mm: 12, placement: top });
    expect(s3.selectedId).toBe(s3.overlays[0].id);
    expect(s3.hover).toBeNull();
    // пока наложение выбрано, плашка под курсором не появляется
    expect(reduce(s3, { type: "hover", placement: side }).hover).toBeNull();
  });

  it("в инструментах «Цвет» и «Готово» клик ничего не ставит", () => {
    const s = run([{ type: "tool", tool: "color" }, { type: "place", placement: top }]);
    expect(s.overlays).toHaveLength(0);
  });

  it("update правит выбранное и держит границы; move переносит; remove снимает выбор", () => {
    const placed = run([{ type: "place", placement: top }]);
    const id = placed.overlays[0].id;
    const s = reduce(placed, { type: "update", id, patch: { size_mm: 999, depth_mm: 0.01, text: "x".repeat(50) } });
    expect(s.overlays[0].size_mm).toBe(200);
    expect(s.overlays[0].depth_mm).toBe(0.2);
    expect(s.overlays[0].text).toHaveLength(40);
    expect(activeDraft(s)).toBe(s.overlays[0]);
    const moved = reduce(s, { type: "move", id, placement: side });
    expect(moved.overlays[0].placement).toBe(side);
    const removed = reduce(moved, { type: "remove", id });
    expect(removed.overlays).toHaveLength(0);
    expect(removed.selectedId).toBeNull();
    expect(selectedOverlay(removed)).toBeNull();
    expect(activeDraft(removed)).toBe(removed.draft);
  });

  it("смена инструмента снимает выбор и переключает вид черновика", () => {
    const s = run([{ type: "place", placement: top }, { type: "tool", tool: "logo" }]);
    expect(s.selectedId).toBeNull();
    expect(s.draft.kind).toBe("logo");
    expect(reduce(s, { type: "tool", tool: "text" }).draft.kind).toBe("text");
  });

  it("хранилище уведомляет подписчиков и молчит, если состояние не изменилось", () => {
    const store = createEditorStore();
    let calls = 0;
    const off = store.subscribe(() => (calls += 1));
    store.dispatch({ type: "gizmo", gizmo: "rotate" });
    store.dispatch({ type: "place", placement: top });
    expect(calls).toBe(2);
    expect(store.getState().gizmo).toBe("rotate");
    store.dispatch({ type: "tool", tool: "color" });
    store.dispatch({ type: "place", placement: top }); // ничего не меняет
    expect(calls).toBe(3);
    off();
    store.dispatch({ type: "gizmo", gizmo: "scale" });
    expect(calls).toBe(3);
  });
});

describe("контракт API", () => {
  it("toEmbossParams кладёт размещение в placement вместе с размером, глубиной и режимом", () => {
    const s = run([{ type: "draft", patch: { text: " Маше ", mode: "engraved", depth_mm: 0.5 } }, { type: "place", placement: side }]);
    const params = toEmbossParams(s.overlays[0]);
    expect(params).toMatchObject({
      kind: "text",
      text: "Маше",
      style: "engraved",
      size_mm: 10,
      depth_mm: 0.5,
      face: "front",
      dx: 0,
      dy: 0,
      angle: 0,
      placement: { point: [5, 0, 3], normal: [1, 0, 0], up: [0, 0, 1], size_mm: 10, depth_mm: 0.5, mode: "engraved" },
    });
  });

  it("overlayProblem объясняет, почему нельзя отправить", () => {
    expect(overlayProblem(null)).toMatch(/Поставьте/);
    const s = run([{ type: "place", placement: top }]);
    expect(overlayProblem(s.overlays[0])).toMatch(/Введите текст/);
    const ok = reduce(s, { type: "update", id: s.overlays[0].id, patch: { text: "Привет" } });
    expect(overlayProblem(ok.overlays[0])).toBeNull();
    const logo = run([{ type: "tool", tool: "logo" }, { type: "place", placement: top }]);
    expect(overlayProblem(logo.overlays[0])).toMatch(/загрузите логотип/);
    expect(overlayProblem(logo.overlays[0], true)).toBeNull();
  });

  it("overlayFromParams возвращает прошлую надпись: туда-обратно через toEmbossParams", () => {
    const s = run([{ type: "draft", patch: { text: "Маше", mode: "engraved", depth_mm: 0.5, font: "serif", bold: false, size_mm: 14 } }, { type: "place", placement: side }]);
    const params = toEmbossParams(s.overlays[0]);
    const back = overlayFromParams("abc123", params as unknown as Record<string, unknown>);
    expect(back).toMatchObject({
      id: "job-abc123",
      kind: "text",
      text: "Маше",
      font: "serif",
      bold: false,
      size_mm: 14,
      depth_mm: 0.5,
      mode: "engraved",
      placement: { point: [5, 0, 3], normal: [1, 0, 0], up: [0, 0, 1] },
    });
  });

  it("overlayFromParams: старая форма без placement — null", () => {
    expect(overlayFromParams("j", { kind: "text", text: "А", face: "front" })).toBeNull();
    expect(overlayFromParams("j", { kind: "logo", face: "front" })).toBeNull();
    expect(overlayFromParams("j", { kind: "text", placement: { point: [0, 0], normal: [0, 0, 1], up: [0, 1, 0] } })).toBeNull();
    expect(overlayFromParams("j", null)).toBeNull();
  });
});

describe("restore (B60c)", () => {
  it("кладёт наложение в стор, выбирает его и не дублирует при повторе", () => {
    const o = overlayFromParams("j1", { kind: "text", text: "Hi", placement: { point: [0, 0, 10], normal: [0, 0, 1], up: [0, 1, 0], size_mm: 8, depth_mm: 1, mode: "raised" } })!;
    const s1 = run([{ type: "tool", tool: "color" }, { type: "restore", overlay: o }]);
    expect(s1.tool).toBe("text");
    expect(s1.overlays).toHaveLength(1);
    expect(selectedOverlay(s1)?.text).toBe("Hi");
    expect(activeDraft(s1).size_mm).toBe(8);
    expect(reduce(s1, { type: "restore", overlay: o })).toBe(s1);
  });
});

describe("editAgainHref (B60c)", () => {
  const placement = { point: [0, 0, 10], normal: [0, 0, 1], up: [0, 1, 0], size_mm: 8, depth_mm: 1, mode: "raised" };
  it("ведёт в редактор исходной модели с job_id", () => {
    expect(editAgainHref({ parent_id: "p1", job_id: "j9", params: { kind: "text", text: "A", placement } })).toBe("/upload/p1/edit?overlay=j9");
  });
  it("логотип из редактора (B62) — тоже со ссылкой", () => {
    expect(editAgainHref({ parent_id: "p1", job_id: "j9", params: { kind: "logo", placement } })).toBe("/upload/p1/edit?overlay=j9");
  });
  it("старая форма — без ссылки", () => {
    expect(editAgainHref({ parent_id: "p1", job_id: "j9", params: { kind: "text", text: "A", face: "top" } })).toBeNull();
    expect(editAgainHref({ parent_id: "p1", job_id: "j9", params: { kind: "logo", face: "top" } })).toBeNull();
    expect(editAgainHref(undefined)).toBeNull();
  });
});

describe("previewColor (B61)", () => {
  it("меняет цвет просмотра, мусор игнорирует", () => {
    const s1 = reduce(INITIAL_STATE, { type: "previewColor", color: "#2e86de" });
    expect(s1.previewColor).toBe("#2e86de");
    expect(reduce(s1, { type: "previewColor", color: "red" })).toBe(s1);
  });
});

describe("логотип (B62)", () => {
  it("инструмент «Логотип» ставит ширину 20 мм, «Текст» — снова 10 мм", () => {
    const s = run([{ type: "tool", tool: "logo" }]);
    expect(s.draft).toMatchObject({ kind: "logo", size_mm: 20 });
    expect(reduce(s, { type: "tool", tool: "text" }).draft).toMatchObject({ kind: "text", size_mm: 10 });
    // Повторный выбор того же инструмента размер не сбрасывает.
    const custom = reduce(s, { type: "draft", patch: { size_mm: 33 } });
    expect(reduce(custom, { type: "tool", tool: "logo" }).draft.size_mm).toBe(33);
  });

  it("действие logo кладёт и убирает SVG", () => {
    const s = run([{ type: "logo", logo: { name: "a.svg", svg: "<svg/>" } }]);
    expect(s.logo?.name).toBe("a.svg");
    expect(reduce(s, { type: "logo", logo: null }).logo).toBeNull();
  });

  it("логотип туда-обратно: toEmbossParams → overlayFromParams", () => {
    const s = run([{ type: "tool", tool: "logo" }, { type: "draft", patch: { size_mm: 25, mode: "engraved" } }, { type: "place", placement: top }]);
    const params = toEmbossParams(s.overlays[0]);
    expect(params).toMatchObject({ kind: "logo", text: "", size_mm: 25, style: "engraved" });
    const back = overlayFromParams("j2", params as unknown as Record<string, unknown>)!;
    expect(back).toMatchObject({ kind: "logo", size_mm: 25, mode: "engraved", text: "" });
    const restored = run([{ type: "restore", overlay: back }]);
    expect(restored.tool).toBe("logo");
    expect(restored.draft.kind).toBe("logo");
  });
});

describe("?tool= в ссылке на редактор (B62a)", () => {
  it("text/logo/color — инструмент, остальное — null", () => {
    expect(toolFromParam("logo")).toBe("logo");
    expect(toolFromParam("color")).toBe("color");
    expect(toolFromParam("text")).toBe("text");
    expect(toolFromParam("done")).toBeNull();
    expect(toolFromParam("<x>")).toBeNull();
    expect(toolFromParam(null)).toBeNull();
  });
});

describe("история и несколько наложений (B65)", () => {
  const placed = run([
    { type: "draft", patch: { text: "А" } },
    { type: "place", placement: top },
    { type: "draft", patch: { text: "Б" } },
    { type: "select", id: null },
    { type: "place", placement: side },
  ]);
  const [a, b] = placed.overlays;

  it("отменить / повторить постановку и удаление", () => {
    expect(placed.overlays.map((o) => o.text)).toEqual(["А", "Б"]);
    const u1 = reduce(placed, { type: "undo" });
    expect(u1.overlays.map((o) => o.text)).toEqual(["А"]);
    expect(u1.selectedId).toBeNull(); // выбранное «Б» исчезло — выбор снят
    const r1 = reduce(u1, { type: "redo" });
    expect(r1.overlays).toEqual(placed.overlays);
    const removed = reduce(r1, { type: "remove", id: a.id });
    expect(removed.overlays).toEqual([b]);
    expect(removed.future).toEqual([]);
    expect(reduce(removed, { type: "undo" }).overlays).toEqual(placed.overlays);
    // пустая история — ничего не меняется
    expect(reduce(INITIAL_STATE, { type: "undo" })).toBe(INITIAL_STATE);
    expect(reduce(placed, { type: "redo" })).toBe(placed);
  });

  it("набор текста и ползунок — один шаг, перемещения — каждое своё", () => {
    let s = reduce(placed, { type: "select", id: a.id });
    for (const text of ["А", "Ан", "Аня"]) s = reduce(s, { type: "update", id: a.id, patch: { text } });
    for (const size_mm of [11, 12, 13]) s = reduce(s, { type: "update", id: a.id, patch: { size_mm } });
    s = reduce(s, { type: "move", id: a.id, placement: side });
    s = reduce(s, { type: "move", id: a.id, placement: top });
    const steps = [s];
    while (steps[steps.length - 1].past.length > placed.past.length) steps.push(reduce(steps[steps.length - 1], { type: "undo" }));
    // 2 перемещения + размер + текст = 4 шага назад к исходному
    expect(steps).toHaveLength(5);
    expect(steps[3].overlays[0].text).toBe("Аня");
    expect(steps[3].overlays[0].size_mm).toBe(10);
    expect(steps[4].overlays).toEqual(placed.overlays);
  });

  it("порядок: вверх/вниз, за край — без изменений", () => {
    const s = reduce(placed, { type: "reorder", id: b.id, dir: -1 });
    expect(s.overlays.map((o) => o.text)).toEqual(["Б", "А"]);
    expect(reduce(s, { type: "reorder", id: b.id, dir: -1 })).toBe(s);
    expect(reduce(s, { type: "undo" }).overlays.map((o) => o.text)).toEqual(["А", "Б"]);
  });

  it("выбор логотипа на инструменте «Текст» переключает панель на «Логотип»", () => {
    const s = run([{ type: "tool", tool: "logo" }, { type: "place", placement: top }, { type: "tool", tool: "text" }]);
    const logoId = s.overlays[0].id;
    const sel = reduce(s, { type: "select", id: logoId });
    expect(sel.tool).toBe("logo");
    expect(selectedOverlay(sel)?.kind).toBe("logo");
  });

  it("restore не попадает в историю", () => {
    const o = overlayFromParams("j1", toEmbossParams(a))!;
    const s = reduce(INITIAL_STATE, { type: "restore", overlay: o });
    expect(s.past).toEqual([]);
  });

  it("тело запроса: первое — params, остальные — more; обратно — все по порядку", () => {
    const body = toEmbossBody(placed.overlays)!;
    expect(body.params.text).toBe("А");
    expect(body.more.map((m) => m.text)).toEqual(["Б"]);
    expect(toEmbossBody([])).toBeNull();
    const back = overlaysFromParams("j9", { ...body.params, more: body.more });
    expect(back.map((o) => [o.id, o.text])).toEqual([["job-j9", "А"], ["job-j9-1", "Б"]]);
    expect(overlaysFromParams("j9", { kind: "text", text: "x" })).toEqual([]);
  });

  it("проблемы: пустая надпись с номером, лимит", () => {
    const empty = reduce(placed, { type: "update", id: b.id, patch: { text: " " } });
    expect(overlaysProblem(empty.overlays)).toMatch(/^2\. Надпись \(пустая\): Введите текст/);
    expect(overlaysProblem(placed.overlays)).toBeNull();
    expect(overlaysProblem([])).toMatch(/Поставьте наложение/);
    expect(overlaysProblem(Array(MAX_OVERLAYS + 1).fill(a))).toMatch(/Не больше 10/);
  });
});

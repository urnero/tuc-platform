import { describe, expect, it } from "vitest";
import { makePlacement } from "./math";
import {
  activeDraft,
  createEditorStore,
  INITIAL_STATE,
  editAgainHref,
  overlayFromParams,
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

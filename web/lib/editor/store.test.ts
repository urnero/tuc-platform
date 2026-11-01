import { describe, expect, it } from "vitest";
import { makePlacement } from "./math";
import {
  activeDraft,
  createEditorStore,
  INITIAL_STATE,
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
    expect(overlayProblem(logo.overlays[0])).toMatch(/логотип/);
  });
});

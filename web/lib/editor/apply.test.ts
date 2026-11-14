import { describe, expect, it, vi } from "vitest";
import { isWorking, pollJob, startApply } from "./apply";
import { makePlacement } from "./math";
import { createEditorStore } from "./store";

const top = makePlacement([0, 0, 7], [0, 0, 1], [0, 1, 0]);

/** Хранилище с одной надписью «Маше» на верхней грани. */
function storeWithText(text = "Маше") {
  const store = createEditorStore();
  store.dispatch({ type: "draft", patch: { text } });
  store.dispatch({ type: "place", placement: top });
  return store;
}

const job = { id: "j1", upload_id: "u1", status: "queued", warnings: [], result_upload_id: null };

describe("«Применить» / «Готово» в редакторе (QA 2026-11-08)", () => {
  it("отправляет все наложения одним POST и возвращает задание", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(job), { status: 202 }));
    const res = await startApply("u1", storeWithText(), fetchMock as unknown as typeof fetch);
    expect(res).toEqual({ job });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/uploads/u1/embosses");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.params.text).toBe("Маше");
    expect(body.more).toEqual([]);
  });

  it("без наложений или с пустым текстом — ошибка без запроса", async () => {
    const fetchMock = vi.fn();
    const empty = await startApply("u1", createEditorStore(), fetchMock as unknown as typeof fetch);
    expect("error" in empty && empty.error).toBeTruthy();
    const blank = await startApply("u1", storeWithText("   "), fetchMock as unknown as typeof fetch);
    expect("error" in blank && blank.error).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("422 с ошибками полей — их текст; другая ошибка — detail или код; нет сети — сообщение", async () => {
    const f422 = vi.fn(async () => new Response(JSON.stringify({ detail: { errors: { text: "Слишком длинно." } } }), { status: 422 }));
    expect(await startApply("u1", storeWithText(), f422 as unknown as typeof fetch)).toEqual({ error: "Слишком длинно." });
    const f500 = vi.fn(async () => new Response("oops", { status: 500 }));
    expect(await startApply("u1", storeWithText(), f500 as unknown as typeof fetch)).toEqual({ error: "Ошибка 500." });
    const fNet = vi.fn(async () => {
      throw new Error("Failed to fetch");
    });
    expect(await startApply("u1", storeWithText(), fNet as unknown as typeof fetch)).toEqual({ error: "Failed to fetch" });
  });

  it("опрос: свежее задание; сервер не ответил — null", async () => {
    const done = { ...job, status: "done", result_upload_id: "u2" };
    const ok = vi.fn(async () => new Response(JSON.stringify(done)));
    expect(await pollJob("u1", "j1", ok as unknown as typeof fetch)).toEqual(done);
    expect((ok.mock.calls[0] as unknown as [string])[0]).toBe("/api/v1/uploads/u1/embosses/j1");
    const bad = vi.fn(async () => new Response("", { status: 502 }));
    expect(await pollJob("u1", "j1", bad as unknown as typeof fetch)).toBeNull();
  });

  it("«Наносим…» — пока задание в очереди или собирается", () => {
    expect(isWorking(null)).toBe(false);
    expect(isWorking({ ...job, status: "queued" } as never)).toBe(true);
    expect(isWorking({ ...job, status: "running" } as never)).toBe(true);
    expect(isWorking({ ...job, status: "done" } as never)).toBe(false);
    expect(isWorking({ ...job, status: "failed" } as never)).toBe(false);
  });
});

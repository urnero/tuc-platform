"use client";

/**
 * Телефон в редакторе (B60b, docs/EDITOR.md): на узком экране гизмо крупнее, кнопки панели
 * крупнее (под палец), под окном — подсказка, что тянуть. «Телефон» = ширина меньше 768 px
 * (та же граница, что `md:` у Tailwind, по ней же меняется раскладка страницы).
 */

import { useSyncExternalStore } from "react";
import type { Gizmo } from "./store";

/** Ширина окна, с которой начинается раскладка «десктоп» (Tailwind `md`). */
export const DESKTOP_MIN_WIDTH = 768;

export const PHONE_QUERY = `(max-width: ${DESKTOP_MIN_WIDTH - 0.02}px)`;

export function isPhoneWidth(width: number): boolean {
  return width < DESKTOP_MIN_WIDTH;
}

/** Размер гизмо TransformControls: на телефоне стрелки крупнее, чтобы попасть пальцем. */
export function gizmoSize(phone: boolean): number {
  return phone ? 1.4 : 0.8;
}

/** Подсказка под окном на телефоне: что делать с гизмо в текущем режиме. */
export function gizmoHint(gizmo: Gizmo, kind: "text" | "logo" = "text"): string {
  const [it, onIt] = kind === "logo" ? ["логотип", "логотипе"] : ["надпись", "надписи"];
  if (gizmo === "rotate") return `Тяните дугу, чтобы повернуть ${it}`;
  if (gizmo === "scale") return `Тяните квадратики или разведите два пальца на ${onIt} — размер`;
  return `Тяните ${it} пальцем или стрелки; двумя пальцами — размер`;
}

function subscribe(onChange: () => void) {
  const mq = window.matchMedia(PHONE_QUERY);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

/** true, если экран узкий (телефон). На сервере — false (раскладка десктопа). */
export function useIsPhone(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(PHONE_QUERY).matches,
    () => false,
  );
}

/**
 * Абзац-подсказка в панели надписи/логотипа (QA 08.11). На телефоне нет наведения мышью,
 * поэтому говорим «коснитесь», а не «наведите и нажмите»; на десктопе — как было.
 */
export function panelHint(o: {
  kind: "text" | "logo";
  phone: boolean;
  selected: boolean;
  hasLogo: boolean;
  count: number;
}): string {
  const logo = o.kind === "logo";
  const what = logo ? "Логотип" : "Надпись";
  const it = what.toLowerCase();
  if (o.selected) {
    return o.phone
      ? `${what} выбран${logo ? "" : "а"}: тяните пальцем по поверхности, двумя пальцами — размер.`
      : `${what} выбран${logo ? "" : "а"}: тяните мышью по поверхности или стрелки гизмо.`;
  }
  if (logo && !o.hasLogo) {
    return `Загрузите SVG-логотип, затем ${o.phone ? "коснитесь модели" : "нажмите на модель"} — он встанет в эту точку и прилипнет к поверхности.`;
  }
  if (o.count === 0) {
    return o.phone
      ? `Коснитесь модели — ${it} встанет в эту точку и прилипнет к поверхности.`
      : `Наведите на модель и нажмите — ${it} встанет в эту точку и прилипнет к поверхности.`;
  }
  return o.phone
    ? `Коснитесь ${logo ? "логотипа" : "надписи"}, чтобы изменить, или свободного места модели — поставить ещё.`
    : `Нажмите на ${it}, чтобы изменить, или на свободное место модели — поставить ещё.`;
}

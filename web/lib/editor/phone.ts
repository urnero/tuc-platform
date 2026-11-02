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
export function gizmoHint(gizmo: Gizmo): string {
  if (gizmo === "rotate") return "Тяните дугу, чтобы повернуть надпись";
  if (gizmo === "scale") return "Тяните квадратики или разведите два пальца на надписи — размер";
  return "Тяните надпись пальцем или стрелки; двумя пальцами — размер";
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

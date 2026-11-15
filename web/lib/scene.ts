/**
 * Цвета 3D-сцены (окно просмотра модели и окно редактора) под тему сайта.
 *
 * Раньше фон был всегда тёмным (#1a2220) с бирюзовой сеткой — в светлой теме это тёмный
 * прямоугольник на светлой странице. Теперь цвета берутся из токенов globals.css:
 *   фон — --surface, мелкая сетка — --line, крупная сетка (каждые 5–10 клеток) — --steel.
 * Тема меняется переключателем в шапке (атрибут data-theme на <html>) или системной
 * настройкой — хук useSceneColors() следит за обоими и перерисовывает сцену.
 */

import { useEffect, useState } from "react";
import { effectiveTheme, parseTheme } from "./ui";

export type SceneColors = { background: string; cell: string; section: string };

/** Запасные значения, если CSS ещё не применился (совпадают с globals.css). */
export const SCENE_FALLBACK: Record<"light" | "dark", SceneColors> = {
  light: { background: "#f5f2ec", cell: "#d9d3c8", section: "#3e5566" },
  dark: { background: "#17181a", cell: "#34353a", section: "#8fa9bb" },
};

/**
 * Цвета сцены по токенам. `readVar("--surface")` возвращает значение CSS-переменной
 * (в браузере — getComputedStyle); пустое значение → запасной цвет темы.
 */
export function sceneColors(dark: boolean, readVar: (name: string) => string = () => ""): SceneColors {
  const fb = SCENE_FALLBACK[dark ? "dark" : "light"];
  const pick = (name: string, fallback: string) => readVar(name).trim() || fallback;
  return {
    background: pick("--surface", fb.background),
    cell: pick("--line", fb.cell),
    section: pick("--steel", fb.section),
  };
}

/** Тёмная ли сейчас тема: атрибут data-theme на <html> важнее системной настройки. */
export function isDarkTheme(dataTheme: string | null, systemDark: boolean): boolean {
  return effectiveTheme(parseTheme(dataTheme), systemDark) === "dark";
}

function readCurrent(): SceneColors {
  if (typeof window === "undefined") return SCENE_FALLBACK.dark;
  const root = document.documentElement;
  const dark = isDarkTheme(root.getAttribute("data-theme"), window.matchMedia("(prefers-color-scheme: dark)").matches);
  const style = getComputedStyle(root);
  return sceneColors(dark, (name) => style.getPropertyValue(name));
}

/** Хук для компонентов с <Canvas>: цвета сцены, обновляются при смене темы. */
export function useSceneColors(): SceneColors {
  const [colors, setColors] = useState<SceneColors>(() => readCurrent());
  useEffect(() => {
    const update = () => setColors(readCurrent());
    update();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", update);
      obs.disconnect();
    };
  }, []);
  return colors;
}

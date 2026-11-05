/**
 * Когда грузить 3D-просмотр на странице модели (UX perf /upload/[id]).
 *
 * three.js — самый тяжёлый кусок сайта (~1 МБ JS): на телефоне он грузится и компилируется
 * несколько секунд, и всё это время страница «подвисает» перед кнопкой «Рассчитать»
 * (Lighthouse mobile: TBT ≈ 5 с). Поэтому:
 *  - широкий экран (≥ 768 px) и нет «экономии трафика» — 3D грузится сам, но только когда
 *    окно просмотра видно и браузер свободен (после первого кадра);
 *  - телефон или «экономия трафика» — вместо 3D карточка с кнопкой «Показать модель в 3D»,
 *    three.js качается только по нажатию.
 */

/** Ширина, с которой 3D грузится без нажатия (как Tailwind `md`). */
export const AUTO_3D_MIN_WIDTH = 768;

/** Высота заглушки с кнопкой на телефоне, px (сам просмотр — 420 px). */
export const PHONE_PLACEHOLDER_HEIGHT = 160;

export type ViewerEnv = {
  /** window.innerWidth */
  width: number;
  /** navigator.connection?.saveData — включена «экономия трафика». */
  saveData?: boolean;
};

/** true — 3D грузится сам; false — ждём нажатия кнопки. */
export function shouldAutoLoad3D(env: ViewerEnv): boolean {
  if (env.saveData) return false;
  return env.width >= AUTO_3D_MIN_WIDTH;
}

/** Высота заглушки до загрузки 3D: на широком экране — как у готового просмотра (без скачка
 *  вёрстки, CLS), на телефоне — короткая карточка с кнопкой. */
export function placeholderHeight(auto: boolean, viewerHeight = 420): number {
  return auto ? viewerHeight : Math.min(PHONE_PLACEHOLDER_HEIGHT, viewerHeight);
}

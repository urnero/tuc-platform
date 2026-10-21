/** Типы и форматирование результата загрузки модели (ответ POST /api/v1/uploads). */

export type MeshInfo = {
  triangles: number;
  vertices: number;
  bbox_mm: { x: number; y: number; z: number };
  volume_cm3: number;
  surface_cm2: number;
  watertight: boolean;
  repaired: boolean;
  unit_hint: "mm" | "maybe_inches";
  warnings: string[];
};

export type Units = "mm" | "inch";

export type Upload = {
  id: string;
  original_name: string;
  ext: "stl" | "3mf";
  size_bytes: number;
  created_at: string;
  /** В каких единицах координаты файла. Числа в mesh всегда в мм. */
  units: Units;
  mesh: MeshInfo;
  /** «catalog» — копия модели из каталога (B20); «editor» — модель, построенная в редакторе (B21). */
  source?: "catalog" | "editor";
  catalog?: { slug: string; title: string; material: string };
  editor?: {
    slug: string;
    title: string;
    material: string;
    build_id: string;
    params: Record<string, number | boolean | string>;
    /** Параметры словами (считает API): «Внешний диаметр 20 мм, Форма: Круглая». */
    summary: string;
  };
};

/** Во сколько раз умножить координаты файла, чтобы получить мм. */
export const UNIT_SCALE: Record<Units, number> = { mm: 1, inch: 25.4 };

export const MAX_UPLOAD_MB = 100;
export const ALLOWED_EXT = ["stl", "3mf"] as const;

/** Расширение файла в нижнем регистре без точки: «Деталь.STL» → «stl». */
export function fileExt(name: string): string {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

/** Проверка до отправки на сервер. Возвращает текст ошибки или null. */
export function validateFile(name: string, sizeBytes: number): string | null {
  const ext = fileExt(name);
  if (!(ALLOWED_EXT as readonly string[]).includes(ext)) {
    return "Поддерживаются только файлы STL и 3MF.";
  }
  if (sizeBytes <= 0) return "Файл пустой.";
  if (sizeBytes > MAX_UPLOAD_MB * 1024 * 1024) return `Файл больше ${MAX_UPLOAD_MB} МБ.`;
  return null;
}

function fmtNum(v: number, digits: number): string {
  const rounded = Number(v.toFixed(digits));
  return (Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(digits)).replace(".", ",");
}

/** «20 × 30 × 40 мм» или, если показываем в дюймах, «0,79 × 1,18 × 1,57″». */
export function formatDims(bbox: MeshInfo["bbox_mm"], show: Units = "mm"): string {
  if (show === "inch") {
    const f = (v: number) => fmtNum(v / 25.4, 2);
    return `${f(bbox.x)} × ${f(bbox.y)} × ${f(bbox.z)}″`;
  }
  const f = (v: number) => fmtNum(v, 1);
  return `${f(bbox.x)} × ${f(bbox.y)} × ${f(bbox.z)} мм`;
}

/** Размер файла: 1536 → «1,5 КБ», 2 097 152 → «2,0 МБ». */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1).replace(".", ",")} КБ`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} МБ`;
}

/** Код предупреждения с сервера → текст для клиента. */
export const WARNING_TEXT: Record<string, string> = {
  holes_filled: "В сетке были дыры — мы закрыли их автоматически. Проверьте модель в просмотре.",
  not_watertight:
    "Сетка не замкнута (есть дыры). Объём и цена могут быть неточными; лучше починить модель.",
  tiny_maybe_inches:
    "Модель очень маленькая. Возможно, файл сохранён в дюймах — проверьте единицы измерения.",
  huge_check_units: "Модель больше метра. Проверьте единицы измерения в файле.",
  exceeds_print_bed: "Модель не помещается в принтер целиком. Напишем вам о вариантах печати по частям.",
  zero_volume: "У модели нулевой объём — похоже, это не тело, а поверхность.",
};

export function warningText(code: string): string {
  return WARNING_TEXT[code] ?? code;
}

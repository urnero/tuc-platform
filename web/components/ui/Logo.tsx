/**
 * Логотип BroPrint (B40) из web/public/brand/. Для светлого фона — обычный файл, для тёмной
 * темы — *-light.svg; переключаются CSS-классами по data-theme / prefers-color-scheme (см. ниже),
 * чтобы не тащить состояние темы в серверный компонент.
 */

import Image from "next/image";

type Props = { kind?: "lockup" | "mark" | "wordmark"; height?: number; className?: string };

// Размеры исходных SVG (viewBox), чтобы Next не ругался на отсутствие width/height.
const SIZES = { lockup: [478, 120], mark: [120, 120], wordmark: [340, 120] } as const;

export default function Logo({ kind = "lockup", height = 32, className }: Props) {
  const [w, h] = SIZES[kind];
  const width = Math.round((w / h) * height);
  const alt = kind === "mark" ? "BroPrint" : "BroPrint — семейная мастерская 3D-печати";
  return (
    <span className={className} style={{ display: "inline-flex", height }}>
      <Image src={`/brand/broprint-${kind}.svg`} alt={alt} width={width} height={height} className="logo-light" priority />
      <Image src={`/brand/broprint-${kind}-light.svg`} alt="" aria-hidden width={width} height={height} className="logo-dark" priority />
    </span>
  );
}

/**
 * Кнопка дизайн-системы (B40). Варианты: primary — оранжевая (одно главное действие на экране),
 * secondary — с рамкой, ghost — только текст. Если передать href — это ссылка в виде кнопки.
 * Классы описаны в app/globals.css (.btn*), их собирает lib/ui.ts::buttonClass.
 */

import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { buttonClass, type ButtonSize, type ButtonVariant } from "@/lib/ui";

type Common = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
};

type AsLink = Common & { href: string; target?: string; rel?: string; download?: string | boolean };
type AsButton = Common & { href?: undefined } & ButtonHTMLAttributes<HTMLButtonElement>;

export default function Button(props: AsLink | AsButton) {
  const { variant = "primary", size = "md", className, children } = props;
  const cls = buttonClass(variant, size, className);
  if (typeof props.href === "string") {
    const { href, target, rel, download } = props;
    return (
      <Link href={href} target={target} rel={rel} download={download} className={cls}>
        {children}
      </Link>
    );
  }
  // Пропсы самой кнопки (href/variant/size/className/children) в DOM не передаём.
  const rest: Record<string, unknown> = { ...props };
  for (const k of ["href", "variant", "size", "className", "children", "type"]) delete rest[k];
  return (
    <button type={(props as AsButton).type ?? "button"} className={cls} {...rest}>
      {children}
    </button>
  );
}

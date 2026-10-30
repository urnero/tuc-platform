/**
 * Карточка (B40): белая плашка с тонкой рамкой (tone="raised", по умолчанию)
 * или «песок» для изделий и фото (tone="sand"). Классы — app/globals.css.
 */

import type { HTMLAttributes } from "react";
import { createElement } from "react";
import { cx } from "@/lib/ui";

type Props = HTMLAttributes<HTMLElement> & { tone?: "raised" | "sand"; as?: "div" | "section" | "article" | "li" };

export default function Card({ tone = "raised", as: Tag = "div", className, children, ...rest }: Props) {
  return createElement(Tag, { className: cx(tone === "sand" ? "card-sand" : "card", className), ...rest }, children);
}

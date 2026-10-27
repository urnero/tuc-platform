/**
 * Поле ввода с подписью (B40): label + <input> (или <textarea> при multiline) + подсказка/ошибка под ним.
 * Ошибка подсвечивает рамку (aria-invalid) и читается экранным диктором (aria-describedby).
 * Для <select> — components/ui/Select.tsx.
 */

import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";
import { cx } from "@/lib/ui";

type Base = {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  className?: string;
};

type InputProps = Base & { multiline?: false } & Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "className">;
type TextareaProps = Base & { multiline: true } & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id" | "className">;

/** Подпись под полем: ошибка важнее подсказки. Общая с Select. */
export function FieldNote({ id, hint, error }: { id: string; hint?: string; error?: string }) {
  if (error) {
    return (
      <p id={`${id}-error`} className="text-sm" style={{ color: "var(--danger)" }}>
        {error}
      </p>
    );
  }
  if (hint) {
    return (
      <p id={`${id}-hint`} className="text-sm" style={{ color: "var(--ink-muted)" }}>
        {hint}
      </p>
    );
  }
  return null;
}

export function describedBy(id: string, hint?: string, error?: string): string | undefined {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

export default function Field(props: InputProps | TextareaProps) {
  const { id, label, hint, error, className } = props;
  const a11y = { id, className: "field", "aria-invalid": error ? true : undefined, "aria-describedby": describedBy(id, hint, error) };
  // Пропсы самого Field в DOM не передаём — убираем их из копии.
  const rest: Record<string, unknown> = { ...props };
  for (const k of ["multiline", "id", "label", "hint", "error", "className"]) delete rest[k];
  const control = props.multiline ? <textarea {...a11y} {...rest} /> : <input {...a11y} {...rest} />;
  return (
    <div className={cx("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      {control}
      <FieldNote id={id} hint={hint} error={error} />
    </div>
  );
}

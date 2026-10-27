/**
 * Выпадающий список с подписью (B40). Варианты — массив { value, label }.
 */

import type { SelectHTMLAttributes } from "react";
import { cx } from "@/lib/ui";
import { describedBy, FieldNote } from "./Field";

type Option = { value: string; label: string; disabled?: boolean };

type Props = Omit<SelectHTMLAttributes<HTMLSelectElement>, "id" | "className"> & {
  id: string;
  label: string;
  options: Option[];
  hint?: string;
  error?: string;
  className?: string;
};

export default function Select({ id, label, options, hint, error, className, ...rest }: Props) {
  return (
    <div className={cx("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-sm font-semibold">
        {label}
      </label>
      <select id={id} className="field" aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, hint, error)} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
      <FieldNote id={id} hint={hint} error={error} />
    </div>
  );
}

/**
 * Бейдж статуса заказа (B40): подпись из lib/order.ts::STATUS_LABELS, тон — lib/ui.ts::STATUS_TONES
 * (зелёный только «Готов»/«Выдан», как велит брендбук). Можно передать свой текст и тон.
 */

import { STATUS_LABELS, type OrderStatus } from "@/lib/order";
import { badgeClass, statusTone, type BadgeTone } from "@/lib/ui";

type Props = { status?: OrderStatus; tone?: BadgeTone; className?: string; children?: React.ReactNode };

export default function StatusBadge({ status, tone, className, children }: Props) {
  const t = tone ?? (status ? statusTone(status) : "neutral");
  return <span className={badgeClass(t, className)}>{children ?? (status ? STATUS_LABELS[status] : "")}</span>;
}

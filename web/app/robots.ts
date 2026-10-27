/**
 * /robots.txt (B25): на проде открыто всё, кроме админки, API и личных страниц заказов
 * и загрузок; на staging и localhost — закрыто целиком (см. lib/seo.ts).
 */

import type { MetadataRoute } from "next";
import { robotsRules } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  return robotsRules();
}

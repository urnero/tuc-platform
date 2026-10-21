/**
 * «Контакты» (B13): /contacts. Все значения — из web/lib/company.ts.
 * Пустые поля показываются как «уточняется», а вверху — напоминание владельцу заполнить их.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { Doc, Facts, P, Section } from "@/components/Doc";
import { COMPANY, phoneUrl, requisite, telegramUrl } from "@/lib/company";

export const metadata: Metadata = {
  title: "Контакты — ТУЦ",
  description: "Как связаться со студией 3D-печати ТУЦ в Москве и где забрать заказ.",
  alternates: { canonical: "/contacts" },
};

export default function ContactsPage() {
  const tg = telegramUrl(COMPANY.telegram);
  const tel = phoneUrl(COMPANY.phone);
  const mail = COMPANY.email.trim();
  const unfilled = [COMPANY.email, COMPANY.phone, COMPANY.telegram, COMPANY.pickupAddress].some((v) => v.trim() === "");

  return (
    <Doc title="Контакты" subtitle={`Студия 3D-печати ${COMPANY.brand} · ${COMPANY.city}`}>
      {unfilled && (
        <p
          className="max-w-prose rounded-md border px-4 py-3 text-sm"
          style={{ borderColor: "var(--accent)", color: "var(--muted)" }}
          data-testid="contacts-unfilled"
        >
          Контакты заполняются. Пока студия работает в тестовом режиме — вопросы по заказу можно оставить в
          комментарии при оформлении.
        </p>
      )}

      <Section title="Написать или позвонить">
        <Facts
          rows={[
            {
              label: "Telegram",
              value: tg ? (
                <a href={tg} className="underline underline-offset-2" rel="noopener">
                  @{COMPANY.telegram.replace(/^@/, "")}
                </a>
              ) : (
                requisite("telegram")
              ),
            },
            {
              label: "Телефон",
              value: tel ? (
                <a href={tel} className="underline underline-offset-2">
                  {COMPANY.phone}
                </a>
              ) : (
                requisite("phone")
              ),
            },
            {
              label: "E-mail",
              value: mail ? (
                <a href={`mailto:${mail}`} className="underline underline-offset-2">
                  {mail}
                </a>
              ) : (
                requisite("email")
              ),
            },
            { label: "Отвечаем", value: requisite("hours") },
          ]}
        />
        <P>
          Пишите с номером заказа (вида ТУЦ-12) — так быстрее. Вопрос про модель до заказа — приложите файл или
          ссылку на страницу загрузки.
        </P>
      </Section>

      <Section title="Самовывоз">
        <Facts
          rows={[
            { label: "Адрес", value: requisite("pickupAddress") },
            { label: "Когда", value: requisite("hours") },
          ]}
        />
        <P>
          О готовности сообщим по контактам из заказа; статус виден и на странице заказа. Доставка курьером по Москве
          выбирается при расчёте цены.
        </P>
      </Section>

      <Section title="Документы">
        <P>
          <Link href="/offer" className="underline underline-offset-2">
            Публичная оферта
          </Link>{" "}
          ·{" "}
          <Link href="/policy" className="underline underline-offset-2">
            Политика обработки персональных данных
          </Link>
        </P>
      </Section>
    </Doc>
  );
}

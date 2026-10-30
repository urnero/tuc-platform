import { ymId, ymSnippet } from "@/lib/metrika";

/** Счётчик Яндекс.Метрики (B51). Без NEXT_PUBLIC_YM_ID ничего не рисует. */
export default function Metrika() {
  const id = ymId();
  if (!id) return null;
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: ymSnippet(id) }} />
      <noscript>
        <div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`https://mc.yandex.ru/watch/${id}`} style={{ position: "absolute", left: "-9999px" }} alt="" />
        </div>
      </noscript>
    </>
  );
}

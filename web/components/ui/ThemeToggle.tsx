"use client";

/**
 * Переключатель темы (B40): кнопка в шапке. Пишет data-theme на <html> и в localStorage
 * (ключ lib/ui.ts::THEME_STORAGE_KEY). До гидрации тему выставляет скрипт THEME_INIT_SCRIPT из layout.
 * Пока компонент не смонтирован, иконка — нейтральная, чтобы сервер и клиент совпали.
 */

import { useEffect, useState } from "react";
import { effectiveTheme, nextTheme, parseTheme, THEME_STORAGE_KEY, type Theme } from "@/lib/ui";

function readTheme(): Theme {
  try {
    return parseTheme(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return "system";
  }
}

function systemDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export default function ThemeToggle({ className }: { className?: string }) {
  const [theme, setTheme] = useState<Theme | null>(null); // null — ещё не на клиенте

  useEffect(() => {
    setTheme(readTheme());
  }, []);

  function toggle() {
    const next = nextTheme(theme ?? "system", systemDark());
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* приватный режим — тема останется до перезагрузки */
    }
  }

  const dark = theme !== null && effectiveTheme(theme, systemDark()) === "dark";
  const label = theme === null ? "Переключить тему" : dark ? "Включить светлую тему" : "Включить тёмную тему";

  return (
    <button type="button" onClick={toggle} aria-label={label} title={label} className={className}>
      {dark ? (
        // солнце
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" />
        </svg>
      ) : (
        // месяц
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
        </svg>
      )}
    </button>
  );
}

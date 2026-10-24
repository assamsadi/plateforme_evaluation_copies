"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";

import { routing } from "@/i18n/routing";
import { usePathname, useRouter } from "@/i18n/navigation";

const FLAGS: Record<string, string> = {
  fr: "🇫🇷",
  en: "🇬🇧",
  es: "🇪🇸",
};

export default function LanguageSwitcher() {
  const t = useTranslations("LanguageSwitcher");
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams();

  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectLocale = (nextLocale: string) => {
    setOpen(false);
    router.replace(
      // @ts-expect-error -- pathname vient de next-intl, params peut porter des segments dynamiques non typés ici.
      { pathname, params },
      { locale: nextLocale },
    );
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-full border border-transparent px-3 py-2 text-xl font-medium text-gray-600 transition-colors hover:border-gray-200 hover:bg-gray-50 hover:text-gray-900"
      >
        <span aria-hidden="true">{FLAGS[locale]}</span>
        <span className="hidden sm:inline">{locale.toUpperCase()}</span>
        <svg
          className={`h-4 w-4 text-gray-400 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 10.94l3.71-3.71a.75.75 0 1 1 1.06 1.06l-4.24 4.25a.75.75 0 0 1-1.06 0L5.21 8.29a.75.75 0 0 1 .02-1.08z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="absolute right-0 z-50 mt-2 w-36 overflow-hidden rounded-xl border border-gray-200 bg-white py-1 shadow-lg"
          >
            {routing.locales.map((loc) => (
              <li key={loc}>
                <button
                  type="button"
                  role="option"
                  aria-selected={loc === locale}
                  onClick={() => selectLocale(loc)}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-lg transition-colors ${
                    loc === locale
                      ? "bg-emerald-50 font-semibold text-emerald-700"
                      : "text-gray-600 hover:bg-gray-50"
                  }`}
                >
                  <span aria-hidden="true">{FLAGS[loc]}</span>
                  {t(loc)}
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import Logo from "./logo";
import LanguageSwitcher from "./language-switcher";
import { useAuth } from "@/lib/auth-context";

export default function Header() {
  const t = useTranslations("Header");
  const navT = useTranslations("Nav");
  const { user, isAuthenticated, isLoading, logout } = useAuth();

  const [activeSection, setActiveSection] = useState<string>("hero");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const ids = ["hero", "reassurance", "how-it-works", "competencies"];
    const observers: IntersectionObserver[] = [];
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) {
            setActiveSection(id);
          }
        },
        { rootMargin: "-20% 0px -60% 0px" }
      );
      observer.observe(el);
      observers.push(observer);
    });
    return () => {
      observers.forEach((o) => o.disconnect());
    };
  }, []);

  const navItems = [
    { id: "hero", label: navT("home") },
    { id: "reassurance", label: navT("trust") },
    { id: "how-it-works", label: navT("howItWorks") },
    { id: "competencies", label: navT("competencies") },
  ];

  const authButtons = !isLoading && isAuthenticated && user ? (
    <>
      <span className="hidden text-lg sm:text-xl font-medium text-slate-700 sm:block whitespace-nowrap">
        {t("greeting", { name: user.first_name })}
      </span>
      <button
        type="button"
        onClick={() => logout()}
        className="group inline-flex h-12 sm:h-14 items-center justify-center overflow-hidden whitespace-nowrap rounded-lg bg-emerald-600 px-5 sm:px-6 text-lg sm:text-xl font-medium text-white shadow-sm transition-all hover:bg-emerald-700 active:scale-95 shrink-0"
      >
        {/* Icône visible par défaut */}
        <svg xmlns="http://www.w3.org/2000/svg" className="h-7 w-7 shrink-0 transition-all duration-300 group-hover:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
        </svg>
        {/* Texte visible au survol */}
        <span className="hidden max-w-0 overflow-hidden transition-all duration-300 group-hover:inline group-hover:max-w-xs">
          {t("logout")}
        </span>
      </button>
    </>
  ) : (
    <>
      <Link
        href="/signin"
        className="group inline-flex h-12 sm:h-14 items-center justify-center overflow-hidden whitespace-nowrap rounded-lg bg-emerald-600 px-5 sm:px-6 text-lg sm:text-xl font-medium text-white shadow-sm transition-all hover:bg-emerald-700 active:scale-95 shrink-0"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-7 w-7 shrink-0 group-hover:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><polyline points="10 17 15 12 10 7" /><line x1="15" y1="12" x2="3" y2="12" />
        </svg>
        <span className="hidden group-hover:inline">
          {t("signIn")}
        </span>
      </Link>
      <Link
        href="/signup"
        className="group hidden sm:inline-flex h-12 sm:h-14 items-center justify-center overflow-hidden whitespace-nowrap rounded-lg border border-slate-200 bg-gray-100/90 px-5 sm:px-6 text-lg sm:text-xl font-medium text-emerald-800 transition-all hover:bg-gray-200 active:scale-95 shrink-0"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-7 w-7 shrink-0 group-hover:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><line x1="19" y1="8" x2="19" y2="14" /><line x1="22" y1="11" x2="16" y2="11" />
        </svg>
        <span className="hidden group-hover:inline">
          {t("getStarted")}
        </span>
      </Link>
    </>
  );

  return (
    <header className="sticky top-0 z-30 w-full bg-white/80 backdrop-blur-md border-b border-slate-200/40">
      <div className="relative flex h-28 sm:h-32 w-full items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center shrink-0">
          <Logo />
        </div>

        <nav aria-label="Global" className="hidden md:flex md:absolute md:left-1/2 md:-translate-x-1/2 items-center justify-center">
          <ul className="flex items-center gap-10 text-xl font-medium">
            {navItems.map((item) => {
              const isActive = activeSection === item.id;
              return (
                <li key={item.id}>
                  <Link
                    href={`/#${item.id}`}
                    className={`transition ${
                      isActive ? "font-semibold text-emerald-700" : "text-gray-600 hover:text-gray-900"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="flex items-center justify-end gap-3 sm:gap-4 shrink-0">
          <LanguageSwitcher />

          <div className="flex items-center gap-2.5 sm:gap-3">
            {authButtons}
          </div>

          <div className="block md:hidden">
            <button
              type="button"
              onClick={() => setMobileMenuOpen((value) => !value)}
              aria-expanded={mobileMenuOpen}
              className="rounded-sm bg-gray-100 p-2 text-gray-600 transition hover:text-gray-600/75"
            >
              <span className="sr-only">{t("toggleMenu")}</span>
              <svg
                aria-hidden="true"
                xmlns="http://www.w3.org/2000/svg"
                className="size-5"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth="2"
              >
                {mobileMenuOpen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                )}
              </svg>
            </button>
          </div>
        </div>
      </div>

      {mobileMenuOpen && (
        <nav aria-label="Global mobile" className="border-t border-gray-100 py-3 px-4 md:hidden bg-white/95">
          <ul className="flex flex-col gap-1">
            {navItems.map((item) => (
              <li key={item.id}>
                <Link
                  href={`/#${item.id}`}
                  onClick={() => setMobileMenuOpen(false)}
                  className={`block rounded-lg px-3 py-2 text-sm font-medium ${
                    activeSection === item.id ? "bg-emerald-50 text-emerald-700" : "text-gray-600"
                  }`}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}

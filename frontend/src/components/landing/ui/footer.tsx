import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import Logo from "./logo";

const SECTION_LINKS = [
  { id: "hero", key: "home" },
  { id: "reassurance", key: "trust" },
  { id: "how-it-works", key: "howItWorks" },
  { id: "competencies", key: "competencies" },
] as const;

export default async function Footer() {
  const t = await getTranslations("Footer");
  const navT = await getTranslations("Nav");
  const headerT = await getTranslations("Header");
  const authT = await getTranslations("Auth.signUp");

  return (
    <footer className="relative z-10 border-t border-gray-200/80">
      <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
        <div className="grid gap-10 sm:grid-cols-[1.4fr_1fr_1fr]">
          <div>
            <Logo />
            <p className="mt-4 max-w-xs text-base text-gray-500">{t("tagline")}</p>
          </div>

          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
              {t("sectionsHeading")}
            </h3>
            <ul className="mt-4 space-y-2.5">
              {SECTION_LINKS.map((item) => (
                <li key={item.id}>
                  <Link
                    href={`/#${item.id}`}
                    className="text-base text-gray-600 transition-colors hover:text-emerald-600"
                  >
                    {navT(item.key)}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
              {t("accountHeading")}
            </h3>
            <ul className="mt-4 space-y-2.5">
              <li>
                <Link href="/signin" className="text-base text-gray-600 transition-colors hover:text-emerald-600">
                  {headerT("signIn")}
                </Link>
              </li>
              <li>
                <Link href="/signup" className="text-base text-gray-600 transition-colors hover:text-emerald-600">
                  {authT("title")}
                </Link>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-10 flex flex-col items-center justify-between gap-4 border-t border-gray-200/80 pt-6 sm:flex-row">
          <p className="text-sm text-gray-400">
            © {new Date().getFullYear()} — {t("rights")}
          </p>
        </div>
      </div>
    </footer>
  );
}

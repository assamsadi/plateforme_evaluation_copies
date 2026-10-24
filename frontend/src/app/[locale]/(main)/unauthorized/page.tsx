"use client";

import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { dashboardHomeFor } from "@/navigation/sidebar/sidebar-items";

export default function Page() {
  const t = useTranslations("Unauthorized");
  const { user } = useAuth();

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-background px-4 py-12 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-md text-center">
        <Lock className="mx-auto size-12 text-primary" />
        <h1 className="mt-4 font-bold text-3xl tracking-tight sm:text-4xl">{t("title")}</h1>
        <p className="mt-4 text-muted-foreground">{t("description")}</p>
        <div className="mt-6">
          <Link
            href={dashboardHomeFor(user?.role)}
            className="inline-flex items-center rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground text-sm shadow-xs transition-colors hover:bg-primary/90 focus:outline-hidden focus:ring-2 focus:ring-primary focus:ring-offset-2"
            prefetch={false}
          >
            {t("backHome")}
          </Link>
        </div>
      </div>
    </div>
  );
}

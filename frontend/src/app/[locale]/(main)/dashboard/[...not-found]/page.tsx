"use client";

import { useTranslations } from "next-intl";

export default function DashboardNotFound() {
  const t = useTranslations("DashboardNotFound");

  return (
    <div className="flex h-full flex-col items-center justify-center space-y-2 text-center">
      <h1 className="font-semibold text-2xl">{t("title")}</h1>
      <p className="text-muted-foreground">{t("description")}</p>
    </div>
  );
}

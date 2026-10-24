"use client";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";

import { SettingsTab } from "../_components/settings-tab";

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <SettingsTab />
    </AuthGuard>
  );
}

"use client";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";

import { ModelConfigsTab } from "../_components/model-configs-tab";

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <ModelConfigsTab />
    </AuthGuard>
  );
}

"use client";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";

import { ProviderCredentialsTab } from "../_components/provider-credentials-tab";

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <ProviderCredentialsTab />
    </AuthGuard>
  );
}

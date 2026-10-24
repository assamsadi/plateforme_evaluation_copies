"use client";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";

import { AppealsTab } from "../_components/appeals-tab";
import { ArbitrationHeader } from "../_components/arbitration-header";

function AppealsPageContent() {
  return (
    <div className="flex flex-col gap-5">
      <ArbitrationHeader />
      <AppealsTab />
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <AppealsPageContent />
    </AuthGuard>
  );
}

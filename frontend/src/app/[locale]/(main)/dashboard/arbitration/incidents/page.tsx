"use client";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";

import { ArbitrationHeader } from "../_components/arbitration-header";
import { IncidentsTab } from "../_components/incidents-tab";

function IncidentsPageContent() {
  return (
    <div className="flex flex-col gap-5">
      <ArbitrationHeader />
      <IncidentsTab />
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <IncidentsPageContent />
    </AuthGuard>
  );
}

"use client";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";

import { ArbitrationHeader } from "../_components/arbitration-header";
import { CorrectionsTab } from "../_components/corrections-tab";

function CorrectionsPageContent() {
  return (
    <div className="flex flex-col gap-5">
      <ArbitrationHeader />
      <CorrectionsTab />
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <CorrectionsPageContent />
    </AuthGuard>
  );
}

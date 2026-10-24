"use client";

import { useParams } from "next/navigation";

import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DecisionLogsView } from "@/app/[locale]/(main)/dashboard/exercises/[exerciseId]/_components/decision-logs-view";
import { Link } from "@/i18n/navigation";
import { listQuestionDecisionLogs } from "@/lib/professor-api";

function QuestionDecisionLogsPageContent() {
  const t = useTranslations("VariantsDialog");
  const { exerciseId, questionId } = useParams<{ exerciseId: string; questionId: string }>();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Link
          href={`/dashboard/exercises/${exerciseId}/questions/${questionId}/variants`}
          className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-sm font-medium text-muted-foreground shadow-2xs transition-colors hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          {t("backToVariants")}
        </Link>
      </div>

      <DecisionLogsView
        title={t("decisionLogsTitle")}
        fetchLogs={(accessToken) => listQuestionDecisionLogs(accessToken, questionId, { limit: 100 })}
      />
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <QuestionDecisionLogsPageContent />
    </AuthGuard>
  );
}

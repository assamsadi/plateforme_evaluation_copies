"use client";
import * as React from "react";

import { AlertTriangle, Check, HelpCircle, Info, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { FilterPill, filterPillTriggerCn } from "@/components/ui/filter-pill";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBadge } from "@/components/ui/status-badge";
import { Textarea } from "@/components/ui/textarea";
import { getAgentLabel, getAgentVisual } from "@/lib/agent-visuals";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  answerClarification,
  resolveCoherenceAmbiguityClarification,
  validateAlternativeAnswerClarification,
  type ClarificationSeverity,
  type ReasoningClarificationRequestRead,
} from "@/lib/professor-api";
import { cn } from "@/lib/utils";

import { deriveAgentName, severityBorderClasses, severityTone } from "./data";

const AGENT_ORDER = ["Extraction_Verification_Agent", "Reasoning_Graph_Agent", "Comparative_Evaluation_Agent"] as const;
const SEVERITY_VALUES: ClarificationSeverity[] = ["blocking", "warning", "informational"];

// Une question longue rendait le format tableau illisible, et ouvrir un
// dialog séparé pour une réponse (souvent une ligne) était un aller-retour
// inutile — la réponse/les actions vivent maintenant directement dans la
// carte de la clarification, jamais dans une fenêtre à part.
function ClarificationCard({
  request,
  onResolved,
  locale,
  t,
  tResolve,
  includeType,
}: {
  request: ReasoningClarificationRequestRead;
  onResolved: (request: ReasoningClarificationRequestRead) => void;
  locale: string;
  t: (key: string, values?: Record<string, string | number>) => string;
  tResolve: (key: string) => string;
  includeType: boolean;
}) {
  const [professorAnswer, setProfessorAnswer] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const kind = request.comparative_clarification_kind;

  async function runAction(action: () => Promise<ReasoningClarificationRequestRead>) {
    setError(null);
    setIsSubmitting(true);
    try {
      const updated = await action();
      onResolved(updated);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : tResolve("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleAnswerSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const session = getStoredSession();
    if (!session) return;
    runAction(() => answerClarification(session.accessToken, request.id, professorAnswer));
  }

  function handleAlternativeAnswer(accepted: boolean) {
    const session = getStoredSession();
    if (!session) return;
    runAction(() => validateAlternativeAnswerClarification(session.accessToken, request.id, accepted));
  }

  function handleCoherence(resolvedAs: "coherent" | "incoherent") {
    const session = getStoredSession();
    if (!session) return;
    runAction(() => resolveCoherenceAmbiguityClarification(session.accessToken, request.id, resolvedAs));
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-slate-200/80 bg-slate-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-900/60">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={severityTone[request.severity]} status={t(`severity_${request.severity}`)} className="text-xs" />
          {includeType ? (
            <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
              {request.comparative_clarification_kind
                ? t(`kind_${request.comparative_clarification_kind}`)
                : t("kind_free_text")}
            </span>
          ) : null}
        </div>
        <span className="text-xs font-semibold text-success">{new Date(request.created_at).toLocaleString(locale)}</span>
      </div>

      <div className={cn("flex max-w-[50%] flex-col gap-2 border-l-4 pl-3.5", severityBorderClasses[request.severity])}>
        <p className="text-sm font-semibold whitespace-pre-line italic leading-relaxed text-black dark:text-white">
          {request.agent_question}
        </p>
        {request.unclear_content ? (
          <p className="text-sm italic text-foreground/80">
            <span className="font-semibold not-italic text-foreground">{tResolve("unclearContent")}: </span>
            <span>« {request.unclear_content} »</span>
          </p>
        ) : null}
        {request.proposed_answer ? (
          <p className="text-sm italic text-foreground/80">
            <span className="font-semibold not-italic text-foreground">{tResolve("proposedAnswer")}: </span>
            <span>{request.proposed_answer}</span>
          </p>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-lg border border-danger/20 bg-danger/10 px-3.5 py-2.5 text-xs font-medium text-danger">{error}</div>
      ) : null}

      <hr className="border-slate-200/80 dark:border-zinc-800" />

      {kind === "alternative_answer" ? (
        <div className="flex flex-col gap-2.5">
          <p className="text-sm text-slate-600 dark:text-zinc-400">{tResolve("alternativeAnswerPrompt")}</p>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isSubmitting}
              onClick={() => handleAlternativeAnswer(false)}
              className="h-8 border-danger/20 text-danger hover:bg-danger/10"
            >
              <X className="mr-1 size-3.5" />
              {tResolve("reject")}
            </Button>
            <Button size="sm" variant="skew" className="h-8 px-3 text-sm font-semibold tracking-wide" disabled={isSubmitting} onClick={() => handleAlternativeAnswer(true)}>
              <Check className="mr-1 size-3.5" />
              {isSubmitting ? tResolve("submitting") : tResolve("accept")}
            </Button>
          </div>
        </div>
      ) : kind === "coherence_ambiguity" ? (
        <div className="flex flex-col gap-2.5">
          <p className="text-sm text-slate-600 dark:text-zinc-400">{tResolve("coherencePrompt")}</p>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isSubmitting}
              onClick={() => handleCoherence("incoherent")}
              className="h-8 border-danger/20 text-danger hover:bg-danger/10"
            >
              {tResolve("incoherent")}
            </Button>
            <Button size="sm" variant="skew" className="h-8 px-3 text-sm font-semibold tracking-wide" disabled={isSubmitting} onClick={() => handleCoherence("coherent")}>
              {isSubmitting ? tResolve("submitting") : tResolve("coherent")}
            </Button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleAnswerSubmit} className="flex flex-col gap-2.5">
          <FieldGroup className="max-w-[50%] gap-2">
            <Field className="gap-1.5">
              <FieldLabel htmlFor={`clarification-answer-${request.id}`} className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                {tResolve("professorAnswer")}
              </FieldLabel>
              <Textarea
                id={`clarification-answer-${request.id}`}
                value={professorAnswer}
                onChange={(event) => setProfessorAnswer(event.target.value)}
                rows={2}
                placeholder="Expliquez ou précisez la consigne attendue..."
                required
              />
            </Field>
          </FieldGroup>
          <div className="flex justify-end">
            <Button
              type="submit"
              variant="skew"
              className="h-10 px-6 text-base font-bold tracking-wide"
              disabled={isSubmitting || !professorAnswer.trim()}
            >
              {isSubmitting ? tResolve("submitting") : tResolve("submit")}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

function AgentClarificationsGroup({
  agentName,
  requests,
  onResolved,
  locale,
  t,
  tAgents,
  tResolve,
}: {
  agentName: string;
  requests: ReasoningClarificationRequestRead[];
  onResolved: (request: ReasoningClarificationRequestRead) => void;
  locale: string;
  t: (key: string, values?: Record<string, string | number>) => string;
  tAgents: (key: string) => string;
  tResolve: (key: string) => string;
}) {
  const { icon: AgentIcon, tone } = getAgentVisual(agentName);
  const includeType = agentName === "Comparative_Evaluation_Agent";

  return (
    <Card className="overflow-hidden rounded-2xl border-0 bg-[#F8FBFE] shadow-2xl ring-1 ring-black/10 dark:bg-zinc-900 dark:ring-white/10">
      <div className="flex shrink-0 items-center gap-1.5 border-b border-black/5 px-4 py-3 dark:border-white/10">
        <span className="size-3 rounded-full bg-[#ff605c]" />
        <span className="size-3 rounded-full bg-[#ffbd44]" />
        <span className="size-3 rounded-full bg-[#00ca4e]" />
      </div>
      <CardHeader className="border-b border-black/5 pb-4 pt-4 dark:border-white/10">
        <div className="flex items-center gap-2.5">
          <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", tone)}>
            <AgentIcon className="size-4" />
          </span>
          <div>
            <CardTitle className="text-base font-semibold leading-none text-slate-900 dark:text-zinc-100">
              {getAgentLabel(agentName, tAgents)}
              <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                {requests.length}
              </span>
            </CardTitle>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 p-4">
        {requests.length === 0 ? (
          <div className="rounded-xl border border-slate-100 bg-slate-50/60 py-8 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
            <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("noResults")}</p>
          </div>
        ) : (
          requests.map((request) => (
            <ClarificationCard
              key={request.id}
              request={request}
              onResolved={onResolved}
              locale={locale}
              t={t}
              tResolve={tResolve}
              includeType={includeType}
            />
          ))
        )}
      </CardContent>
    </Card>
  );
}

export function Clarifications({
  requests,
  onResolved,
}: {
  requests: ReasoningClarificationRequestRead[];
  onResolved: (request: ReasoningClarificationRequestRead) => void;
}) {
  const t = useTranslations("Clarifications");
  const tAgents = useTranslations("AgentDecisions");
  const tResolve = useTranslations("ResolveClarificationDialog");
  const locale = useLocale();
  const [searchQuery, setSearchQuery] = React.useState("");
  const [severityFilter, setSeverityFilter] = React.useState<ClarificationSeverity | "All">("All");

  const blockingCount = requests.filter((r) => r.severity === "blocking").length;
  const warningCount = requests.filter((r) => r.severity === "warning").length;
  const informationalCount = requests.filter((r) => r.severity === "informational").length;

  const filteredRequests = React.useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return requests.filter((request) => {
      if (severityFilter !== "All" && request.severity !== severityFilter) return false;
      if (!query) return true;
      const haystack = `${request.agent_question} ${request.unclear_content ?? ""}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [requests, searchQuery, severityFilter]);

  const requestsByAgent = React.useMemo(() => {
    const groups = new Map<string, ReasoningClarificationRequestRead[]>();
    for (const request of filteredRequests) {
      const agentName = deriveAgentName(request);
      const list = groups.get(agentName) ?? [];
      list.push(request);
      groups.set(agentName, list);
    }
    return groups;
  }, [filteredRequests]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <SearchInput
          className="w-full md:w-72"
          placeholder={t("searchPlaceholder")}
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        <FilterPill>
          <Select value={severityFilter} onValueChange={(value) => setSeverityFilter(value as ClarificationSeverity | "All")}>
            <SelectTrigger size="sm" className={filterPillTriggerCn}>
              <span className="font-normal text-slate-400/90 dark:text-zinc-500">{t("columnSeverity")}:</span>
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper" align="start" className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
              <SelectGroup>
                <SelectItem value="All" className="text-sm font-medium">
                  {t("severityAll")}
                </SelectItem>
                {SEVERITY_VALUES.map((value) => (
                  <SelectItem key={value} value={value} className="text-sm font-medium">
                    {t(`severity_${value}`)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </FilterPill>
      </div>

      {/* Résumé par sévérité — utile pour trier ce qui presse (bloquant)
          de ce qui peut attendre (informatif), plutôt qu'un total muet ou
          une liste uniformément grise à parcourir ligne par ligne. */}
      <div className="grid grid-cols-1 gap-4.5 sm:grid-cols-3">
        <Card className="relative overflow-hidden shadow-2xs border-slate-200/90 dark:border-zinc-800">
          <div className="absolute inset-x-0 top-0 h-1 bg-danger" />
          <CardHeader className="flex flex-row items-center justify-between px-5 pt-4.5 pb-2">
            <CardDescription className="text-xs font-bold tracking-wider text-slate-700 uppercase dark:text-zinc-300">
              {t("severity_blocking")}
            </CardDescription>
            <div className="flex size-9 items-center justify-center rounded-xl border border-danger/20 bg-danger/10 text-danger">
              <AlertTriangle className="size-4.5" />
            </div>
          </CardHeader>
          <CardContent className="px-5 pb-5">
            <div className="text-3xl font-bold tracking-tight text-slate-900 tabular-nums dark:text-zinc-100">{blockingCount}</div>
          </CardContent>
        </Card>
        <Card className="relative overflow-hidden shadow-2xs border-slate-200/90 dark:border-zinc-800">
          <div className="absolute inset-x-0 top-0 h-1 bg-warning" />
          <CardHeader className="flex flex-row items-center justify-between px-5 pt-4.5 pb-2">
            <CardDescription className="text-xs font-bold tracking-wider text-slate-700 uppercase dark:text-zinc-300">
              {t("severity_warning")}
            </CardDescription>
            <div className="flex size-9 items-center justify-center rounded-xl border border-warning/20 bg-warning/10 text-warning">
              <HelpCircle className="size-4.5" />
            </div>
          </CardHeader>
          <CardContent className="px-5 pb-5">
            <div className="text-3xl font-bold tracking-tight text-slate-900 tabular-nums dark:text-zinc-100">{warningCount}</div>
          </CardContent>
        </Card>
        <Card className="relative overflow-hidden shadow-2xs border-slate-200/90 dark:border-zinc-800">
          <div className="absolute inset-x-0 top-0 h-1 bg-info" />
          <CardHeader className="flex flex-row items-center justify-between px-5 pt-4.5 pb-2">
            <CardDescription className="text-xs font-bold tracking-wider text-slate-700 uppercase dark:text-zinc-300">
              {t("severity_informational")}
            </CardDescription>
            <div className="flex size-9 items-center justify-center rounded-xl border border-info/20 bg-info/10 text-info">
              <Info className="size-4.5" />
            </div>
          </CardHeader>
          <CardContent className="px-5 pb-5">
            <div className="text-3xl font-bold tracking-tight text-slate-900 tabular-nums dark:text-zinc-100">{informationalCount}</div>
          </CardContent>
        </Card>
      </div>

      {AGENT_ORDER.map((agentName) => (
        <AgentClarificationsGroup
          key={agentName}
          agentName={agentName}
          requests={requestsByAgent.get(agentName) ?? []}
          onResolved={onResolved}
          locale={locale}
          t={t}
          tAgents={tAgents}
          tResolve={tResolve}
        />
      ))}
    </div>
  );
}

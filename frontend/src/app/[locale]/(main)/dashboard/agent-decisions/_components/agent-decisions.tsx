"use client";
import * as React from "react";

import { BrainCircuit, Info } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterPill, filterPillTriggerCn } from "@/components/ui/filter-pill";
import { SearchInput } from "@/components/ui/search-input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { AgentDecisionLogRead } from "@/lib/admin-api";
import { getAgentLabel, getAgentVisual } from "@/lib/agent-visuals";
import { cn } from "@/lib/utils";

import { validationStatusValues } from "./data";

interface ExerciseGroup {
  key: string;
  exerciseTitle: string;
  logs: AgentDecisionLogRead[];
}

// Les 5 types de related_entity_type remontent tous à un exercice (résolu
// côté service, cf. DecisionLogService._resolve_entity_labels) — regrouper
// dessus rend l'écran lisible même avec beaucoup de décisions mêlées de
// plusieurs exercices, gap relevé en test réel (liste plate difficile à
// suivre). "unknown" (sans exercise_id du tout) pour les logs dont le type
// d'entité ne remonte à aucun exercice.
function groupByExercise(
  logs: AgentDecisionLogRead[],
  t: (key: string, values?: Record<string, string>) => string,
): ExerciseGroup[] {
  const byExercise = new Map<string, AgentDecisionLogRead[]>();
  for (const log of logs) {
    const key = log.exercise_id ?? "unknown";
    const list = byExercise.get(key) ?? [];
    list.push(log);
    byExercise.set(key, list);
  }
  return Array.from(byExercise.entries()).map(([key, groupLogs]) => {
    // exercise_id existe mais son titre n'a pas pu être résolu (exercice
    // jamais créé — échec avant persistance, ex. structuration interrompue)
    // — gap relevé en test réel : "Exercice inconnu" identique pour PLUSIEURS
    // groupes distincts, impossible de les différencier sans rouvrir chacun.
    // On garde une référence (id tronqué) directement dans le titre du groupe.
    const fallbackTitle = key === "unknown" ? t("unknownExercise") : t("unknownExerciseRef", { id: key.slice(0, 8) });
    return {
      key,
      exerciseTitle: groupLogs[0].exercise_title ?? fallbackTitle,
      logs: groupLogs,
    };
  });
}

export function AgentDecisions({
  logs,
  onView,
}: {
  logs: AgentDecisionLogRead[];
  onView: (log: AgentDecisionLogRead) => void;
}) {
  const t = useTranslations("AgentDecisions");
  const locale = useLocale();
  const [searchQuery, setSearchQuery] = React.useState("");
  const [validationFilter, setValidationFilter] = React.useState<string>("All");

  const validationOptions = ["All", ...validationStatusValues] as const;
  const validationOptionLabel = (value: (typeof validationOptions)[number]) =>
    value === "All" ? t("validationAll") : t(`validation_${value}`);

  const filteredLogs = React.useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return logs.filter((log) => {
      if (validationFilter !== "All" && log.professor_validation_status !== validationFilter) return false;
      if (!query) return true;
      const haystack =
        `${log.agent_name} ${log.related_entity_type} ${log.entity_label ?? ""} ${log.justification}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [logs, searchQuery, validationFilter]);

  const groups = React.useMemo(() => groupByExercise(filteredLogs, t), [filteredLogs, t]);

  return (
    <Card className="overflow-hidden">
      <div className="h-1 w-full bg-primary" />
      <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
              <BrainCircuit className="size-5" />
            </div>
            <div>
              <CardTitle className="text-base font-bold leading-none text-slate-900 dark:text-zinc-100">
                {t("title")}
                <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-sm font-semibold text-muted-foreground">
                  {logs.length}
                </span>
              </CardTitle>
              <CardDescription className="mt-1 text-base font-medium">{t("description")}</CardDescription>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <SearchInput
            className="w-full md:w-72"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />

          <FilterPill>
            <Select value={validationFilter} onValueChange={setValidationFilter}>
              <SelectTrigger size="sm" className={filterPillTriggerCn}>
                <span className="font-normal text-slate-400/90 dark:text-zinc-500">{t("validationLabel")}</span>
                <SelectValue />
              </SelectTrigger>
              <SelectContent
                position="popper"
                align="start"
                className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700"
              >
                <SelectGroup>
                  {validationOptions.map((option) => (
                    <SelectItem key={option} value={option} className="text-base font-medium">
                      {validationOptionLabel(option)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </FilterPill>
        </div>

        {groups.length === 0 ? (
          <div className="rounded-xl border border-slate-100 bg-slate-50/60 py-10 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
            <p className="text-base font-medium text-slate-400 dark:text-zinc-500">{t("noResults")}</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-100 dark:border-zinc-800">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("columnAgent")}</TableHead>
                  <TableHead>{t("columnDate")}</TableHead>
                  <TableHead className="text-right">{t("columnActions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.map((group) => (
                  <React.Fragment key={group.key}>
                    <TableRow className="bg-slate-50/80 hover:bg-slate-50/80 hover:shadow-none dark:bg-zinc-800/40 dark:hover:bg-zinc-800/40">
                      <TableCell colSpan={3} className="py-2.5 whitespace-normal">
                        <div className="flex items-center gap-2">
                          <span className="text-base font-bold text-slate-900 dark:text-zinc-100">
                            {group.exerciseTitle}
                          </span>
                          <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-sm font-semibold text-muted-foreground">
                            {group.logs.length}
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                    {group.logs.map((log) => (
                      <DecisionRow key={log.id} log={log} onView={onView} locale={locale} t={t} />
                    ))}
                  </React.Fragment>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DecisionRow({
  log,
  onView,
  locale,
  t,
}: {
  log: AgentDecisionLogRead;
  onView: (log: AgentDecisionLogRead) => void;
  locale: string;
  t: (key: string, values?: Record<string, string | number>) => string;
}) {
  const { icon: AgentIcon, tone } = getAgentVisual(log.agent_name);
  const agentLabel = getAgentLabel(log.agent_name, t);

  return (
    <TableRow>
      <TableCell>
        <div className="flex min-w-0 items-center gap-2.5">
          <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-md", tone)}>
            <AgentIcon className="size-4" />
          </span>
          <span className="truncate text-base font-bold text-slate-900 dark:text-zinc-100">{agentLabel}</span>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="shrink-0 text-slate-400 transition-colors hover:text-slate-700 dark:text-zinc-500 dark:hover:text-zinc-200"
              >
                <Info className="size-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="font-mono">
              {log.agent_name} · {log.related_entity_type} #{log.related_entity_id}
            </TooltipContent>
          </Tooltip>
        </div>
      </TableCell>
      <TableCell>
        <span className="text-base font-semibold text-success">{new Date(log.created_at).toLocaleString(locale)}</span>
      </TableCell>
      <TableCell className="text-right">
        <Button size="sm" variant="outline" className="h-8 px-3 text-base font-semibold" onClick={() => onView(log)}>
          {t("viewAction")}
        </Button>
      </TableCell>
    </TableRow>
  );
}

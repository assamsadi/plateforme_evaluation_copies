"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AlertTriangle, CheckCircle2, RefreshCw, Sparkles, User, Users } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { StatusBadge } from "@/components/ui/status-badge";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  detectAndClusterIncidents,
  listPendingIncidents,
  type SubmissionIncidentRead,
} from "@/lib/professor-api";
import { cn } from "@/lib/utils";

import { incidentStatusTone } from "./data";
import { ResolveIncidentDialog } from "./resolve-incident-dialog";
import { type IncidentCluster, ResolveIncidentClusterDialog } from "./resolve-incident-cluster-dialog";

interface ExerciseGroup {
  exerciseId: string;
  exerciseTitle: string;
  standalone: SubmissionIncidentRead[];
  clusters: { root: SubmissionIncidentRead; children: SubmissionIncidentRead[] }[];
}

function groupByExerciseAndCluster(incidents: SubmissionIncidentRead[]): ExerciseGroup[] {
  const byExercise = new Map<string, SubmissionIncidentRead[]>();
  for (const incident of incidents) {
    const list = byExercise.get(incident.exercise_id) ?? [];
    list.push(incident);
    byExercise.set(incident.exercise_id, list);
  }

  return Array.from(byExercise.entries()).map(([exerciseId, group]) => {
    const childrenByParent = new Map<string, SubmissionIncidentRead[]>();
    for (const incident of group) {
      if (!incident.parent_incident_id) continue;
      const list = childrenByParent.get(incident.parent_incident_id) ?? [];
      list.push(incident);
      childrenByParent.set(incident.parent_incident_id, list);
    }

    const clusters: ExerciseGroup["clusters"] = [];
    const standalone: SubmissionIncidentRead[] = [];
    for (const incident of group) {
      if (incident.parent_incident_id) continue;
      const children = childrenByParent.get(incident.id) ?? [];
      if (children.length > 0) {
        clusters.push({ root: incident, children });
      } else {
        standalone.push(incident);
      }
    }

    return { exerciseId, exerciseTitle: group[0].exercise_title, standalone, clusters };
  });
}

export function IncidentsTab() {
  const t = useTranslations("IncidentsTab");
  const locale = useLocale();
  const [incidents, setIncidents] = useState<SubmissionIncidentRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolveTarget, setResolveTarget] = useState<SubmissionIncidentRead | null>(null);
  const [clusterTarget, setClusterTarget] = useState<IncidentCluster | null>(null);
  const [detectingExerciseId, setDetectingExerciseId] = useState<string | null>(null);

  const fetchIncidents = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await listPendingIncidents(session.accessToken);
      setIncidents(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  const groups = useMemo(() => groupByExerciseAndCluster(incidents), [incidents]);

  function handleResolved(resolved: SubmissionIncidentRead) {
    setIncidents((prev) => prev.filter((i) => i.id !== resolved.id));
    toast.success(t("resolveSuccess", { name: resolved.student_full_name }));
  }

  function handleClusterResolved(clusterRootId: string) {
    setIncidents((prev) => prev.filter((i) => i.id !== clusterRootId && i.parent_incident_id !== clusterRootId));
    toast.success(t("clusterResolveSuccess"));
  }

  async function handleDetectCluster(exerciseId: string) {
    const session = getStoredSession();
    if (!session) return;

    setDetectingExerciseId(exerciseId);
    try {
      // detectAndClusterIncidents ne renvoie que l'id du groupe formé (ou
      // null) — le clustering et le rattachement parent/enfants se font
      // côté serveur, jamais une liste d'incidents à fusionner nous-mêmes.
      const result = await detectAndClusterIncidents(session.accessToken, exerciseId);
      await fetchIncidents();
      toast.success(result.root_incident_id ? t("clusterDetected") : t("clusterNotDetected"));
    } catch (detectError) {
      toast.error(detectError instanceof AuthApiError ? detectError.message : t("clusterDetectError"));
    } finally {
      setDetectingExerciseId(null);
    }
  }

  if (error) {
    return (
      <Alert variant="destructive" className="rounded-2xl">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  return (
    <>
      <Card className="overflow-hidden border-slate-200/90 shadow-2xs dark:border-zinc-800">
        <div className="h-1 w-full bg-warning" />
        
        <CardHeader className="border-b border-slate-100 pb-4 pt-4 dark:border-zinc-800">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-xl border border-warning/20 bg-warning/10 text-warning">
                <AlertTriangle className="size-4.5" />
              </div>
              <div>
                <CardTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">
                  {t("title")}
                  {incidents.length > 0 && (
                    <StatusBadge tone="warning" status={`${incidents.length} incident${incidents.length > 1 ? "s" : ""}`} className="ml-2 text-xs" />
                  )}
                </CardTitle>
                <CardDescription className="mt-1 text-sm font-medium">{t("description")}</CardDescription>
              </div>
            </div>

            <Button
              size="sm"
              variant="outline"
              onClick={fetchIncidents}
              disabled={isLoading}
              className="h-8 rounded-lg px-3 text-sm font-semibold"
            >
              <RefreshCw className={cn("mr-1.5 size-3.5", isLoading && "animate-spin")} />
              Actualiser
            </Button>
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-5 p-5">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-center">
              <div className="size-4 animate-spin rounded-full border-2 border-warning border-t-transparent" />
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</p>
            </div>
          ) : groups.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 py-12 text-center dark:border-zinc-800 dark:bg-zinc-800/20">
              <div className="flex size-10 items-center justify-center rounded-full bg-success/10 text-success">
                <CheckCircle2 className="size-5" />
              </div>
              <p className="mt-2 text-sm font-bold text-slate-900 dark:text-zinc-100">Aucun incident à traiter</p>
              <p className="mt-0.5 text-xs font-medium text-slate-500 dark:text-zinc-400">{t("noResults")}</p>
            </div>
          ) : (
            groups.map((group, groupIndex) => (
              <div key={group.exerciseId} className="flex flex-col gap-3.5">
                {groupIndex > 0 ? <Separator className="bg-slate-100 dark:bg-zinc-800" /> : null}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-bold text-slate-900 dark:text-zinc-100">{group.exerciseTitle}</span>
                  {group.standalone.length >= 2 ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleDetectCluster(group.exerciseId)}
                      disabled={detectingExerciseId === group.exerciseId}
                      className="h-8 rounded-lg px-3 text-sm font-semibold"
                    >
                      <Sparkles className="mr-1.5 size-3.5 text-amber-500" />
                      {detectingExerciseId === group.exerciseId ? t("detecting") : t("detectClusterAction")}
                    </Button>
                  ) : null}
                </div>

                {group.clusters.map(({ root, children }) => (
                  <div
                    key={root.id}
                    className="flex flex-col gap-3.5 rounded-xl border border-amber-300/80 bg-amber-50/60 p-4.5 dark:border-amber-900/50 dark:bg-amber-950/30"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <Users className="size-4.5 text-amber-600 dark:text-amber-400" />
                        <span className="text-sm font-bold text-amber-900 dark:text-amber-200">
                          {t("clusterLabel", { count: children.length + 1 })}
                        </span>
                        <Badge variant="outline" className="text-xs font-semibold">
                          {t(`category_${root.category}`)}
                        </Badge>
                      </div>
                      <Button
                        size="sm"
                        variant="skew"
                        className="h-8 px-4 text-sm font-semibold tracking-wide"
                        onClick={() =>
                          setClusterTarget({
                            rootId: root.id,
                            exerciseTitle: group.exerciseTitle,
                            size: children.length + 1,
                          })
                        }
                      >
                        {t("resolveClusterAction")}
                      </Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {[root, ...children].map((member) => (
                        <span
                          key={member.id}
                          className="inline-flex items-center rounded-lg bg-white px-2.5 py-1 text-xs font-bold text-slate-800 shadow-2xs dark:bg-zinc-900 dark:text-zinc-200"
                        >
                          {member.student_full_name}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}

                {group.standalone.map((incident) => (
                  <div
                    key={incident.id}
                    className="flex flex-col gap-3.5 rounded-xl border border-amber-300/80 bg-amber-50/60 p-4.5 transition-colors hover:bg-amber-50/90 dark:border-amber-900/50 dark:bg-amber-950/30"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-slate-200 text-sm font-bold text-slate-800 dark:bg-zinc-800 dark:text-zinc-200">
                          {incident.student_full_name?.[0]?.toUpperCase() || <User className="size-4" />}
                        </div>
                        <div>
                          <p className="text-sm font-bold text-slate-900 dark:text-zinc-100">{incident.student_full_name}</p>
                          <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
                            {t(`category_${incident.category}`)}
                          </span>
                        </div>
                      </div>

                      <StatusBadge tone={incidentStatusTone[incident.status]} status={t(`status_${incident.status}`)} className="text-xs" />
                    </div>

                    <div className="rounded-xl border border-slate-200/90 bg-white p-3.5 text-sm font-medium italic leading-relaxed text-slate-800 dark:border-zinc-700/60 dark:bg-zinc-900 dark:text-zinc-200">
                      <span className="font-bold not-italic text-slate-900 dark:text-zinc-100">Motif : </span>
                      {incident.reason}
                    </div>

                    {incident.incident_occurred_at ? (
                      <p className="text-xs font-semibold text-slate-600 dark:text-zinc-400">
                        {t("occurredAt")}: {new Date(incident.incident_occurred_at).toLocaleString(locale)}
                      </p>
                    ) : null}

                    <div className="flex justify-end border-t border-amber-200/60 pt-3 dark:border-zinc-800">
                      <Button
                        size="sm"
                        variant="skew"
                        className="h-8 px-4 text-sm font-semibold tracking-wide"
                        onClick={() => setResolveTarget(incident)}
                      >
                        {t("resolveAction")}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <ResolveIncidentDialog
        incident={resolveTarget}
        open={Boolean(resolveTarget)}
        onOpenChange={(open) => !open && setResolveTarget(null)}
        onResolved={handleResolved}
      />
      <ResolveIncidentClusterDialog
        cluster={clusterTarget}
        open={Boolean(clusterTarget)}
        onOpenChange={(open) => !open && setClusterTarget(null)}
        onResolved={handleClusterResolved}
      />
    </>
  );
}

"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Cpu, Info, Sparkles, Timer } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/status-badge";
import { type ModelConfigurationRead, type ModelProvider, updateModelConfiguration } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

const providerValues: ModelProvider[] = ["groq", "openai", "azure_openai", "ollama"];

function ModelTaskTooltip({ taskType }: { taskType: string }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="text-slate-400 transition-colors hover:text-slate-700 dark:text-zinc-500 dark:hover:text-zinc-200"
        >
          <Info className="size-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 gap-0 overflow-hidden rounded-xl border-0 bg-[#F8FBFE] p-0 shadow-xl ring-1 ring-black/5 dark:bg-zinc-900 dark:ring-white/10">
        <div className="flex items-center gap-1.5 px-3.5 py-2.5 bg-slate-100/80 dark:bg-zinc-800/80">
          <span className="size-2.5 rounded-full bg-[#ff605c]" />
          <span className="size-2.5 rounded-full bg-[#ffbd44]" />
          <span className="size-2.5 rounded-full bg-[#00ca4e]" />
        </div>
        <div className="flex flex-col gap-1.5 border-t border-black/5 px-4 py-3 text-left font-mono text-sm break-all text-slate-900 dark:border-white/10 dark:text-zinc-100">
          <p className="font-semibold text-slate-500 dark:text-zinc-400">Type de tâche IA :</p>
          <p className="select-all text-emerald-600 dark:text-emerald-400">{taskType}</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function EditModelConfigDialog({
  config,
  open,
  onOpenChange,
  onUpdated,
}: {
  config: ModelConfigurationRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (config: ModelConfigurationRead) => void;
}) {
  const t = useTranslations("EditModelConfigDialog");
  const [provider, setProvider] = useState<ModelProvider>("groq");
  const [modelName, setModelName] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (config) {
      setProvider(config.provider);
      setModelName(config.model_name);
      setTimeoutSeconds(String(config.timeout_seconds));
      setError(null);
    }
  }, [config]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !config) return;

    setIsSubmitting(true);
    try {
      const updated = await updateModelConfiguration(session.accessToken, config.task_type, {
        provider,
        model_name: modelName,
        timeout_seconds: Number(timeoutSeconds),
      });
      onUpdated(updated);
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        style={{ width: "680px", maxWidth: "min(680px, calc(100vw - 2rem))" }}
        className="max-h-[85vh] overflow-hidden p-0 rounded-2xl border-0 bg-[#F8FBFE] shadow-2xl ring-1 ring-black/10 dark:bg-zinc-900 dark:ring-white/10"
      >
        {/* En-tête macOS unifié pour toute la carte */}
        <div className="flex items-center justify-between border-b border-black/5 bg-slate-100/70 px-5 py-3 dark:border-white/10 dark:bg-zinc-800/60">
          <div className="flex items-center gap-2">
            <span className="size-3 rounded-full bg-[#ff605c] shadow-2xs" />
            <span className="size-3 rounded-full bg-[#ffbd44] shadow-2xs" />
            <span className="size-3 rounded-full bg-[#00ca4e] shadow-2xs" />
          </div>
          <span className="font-mono text-sm font-semibold text-slate-500 dark:text-zinc-400 mr-8">
            {config ? config.task_type : "model-config"}
          </span>
        </div>

        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3.5">
                <div className="flex size-13 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary font-bold text-xl shadow-2xs">
                  <Cpu className="size-6" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <DialogTitle className="text-xl font-bold text-slate-900 dark:text-zinc-100">
                      {config ? t("title", { taskType: config.task_type }) : t("titleGeneric")}
                    </DialogTitle>
                    {config ? <ModelTaskTooltip taskType={config.task_type} /> : null}
                  </div>
                  <p className="text-base font-medium text-muted-foreground">Configuration du modèle LLM et latence</p>
                </div>
              </div>

              {config ? (
                <StatusBadge
                  tone={config.is_overridden ? "info" : "neutral"}
                  status={config.is_overridden ? "Personnalisé" : "Défaut"}
                />
              ) : null}
            </div>
          </DialogHeader>

          {config ? (
            <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              {/* Informations Contexte */}
              <div className="rounded-xl border border-black/5 bg-white/80 p-4 shadow-2xs dark:border-white/5 dark:bg-zinc-800/50">
                <div className="flex items-center gap-2 mb-2 pb-2 border-b border-black/5 dark:border-white/5">
                  <Sparkles className="size-4 text-primary" />
                  <span className="text-sm font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                    Paramètres IA actuels
                  </span>
                </div>
                <div className="flex items-center justify-between gap-4 py-1.5 border-b border-black/5 last:border-0 dark:border-white/5">
                  <span className="text-base font-medium text-slate-600 dark:text-zinc-400">Tâche</span>
                  <span className="font-mono text-base font-semibold text-slate-900 dark:text-zinc-100">
                    {config.task_type}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-4 py-1.5 border-b border-black/5 last:border-0 dark:border-white/5">
                  <span className="text-base font-medium text-slate-600 dark:text-zinc-400">Fournisseur actuel</span>
                  <span className="font-mono text-base font-medium text-muted-foreground">{config.provider}</span>
                </div>
              </div>

              {/* Formulaire */}
              <FieldGroup className="gap-3.5">
                <Field className="gap-1.5">
                  <FieldLabel
                    htmlFor="edit-model-provider"
                    className="text-base font-semibold text-slate-800 dark:text-zinc-200"
                  >
                    {t("provider")}
                  </FieldLabel>
                  <Select value={provider} onValueChange={(value) => setProvider(value as ModelProvider)}>
                    <SelectTrigger
                      id="edit-model-provider"
                      className="h-10 rounded-xl border-slate-200 bg-white text-base font-medium dark:border-zinc-700 dark:bg-zinc-800"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {providerValues.map((value) => (
                        <SelectItem key={value} value={value} className="text-base font-medium">
                          {value}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field className="gap-1.5">
                  <FieldLabel
                    htmlFor="edit-model-name"
                    className="text-base font-semibold text-slate-800 dark:text-zinc-200"
                  >
                    {t("modelName")}
                  </FieldLabel>
                  <Input
                    id="edit-model-name"
                    value={modelName}
                    onChange={(event) => setModelName(event.target.value)}
                    required
                    className="h-10 rounded-xl border-slate-200 bg-white font-mono text-base dark:border-zinc-700 dark:bg-zinc-800"
                  />
                </Field>

                <Field className="gap-1.5">
                  <FieldLabel
                    htmlFor="edit-model-timeout"
                    className="text-base font-semibold text-slate-800 dark:text-zinc-200"
                  >
                    <span className="flex items-center gap-1.5">
                      <Timer className="size-3.5 text-slate-500" />
                      {t("timeoutSeconds")}
                    </span>
                  </FieldLabel>
                  <Input
                    id="edit-model-timeout"
                    type="number"
                    min={1}
                    value={timeoutSeconds}
                    onChange={(event) => setTimeoutSeconds(event.target.value)}
                    required
                    className="h-10 rounded-xl border-slate-200 bg-white text-base dark:border-zinc-700 dark:bg-zinc-800"
                  />
                </Field>

                {error ? (
                  <div className="rounded-xl border border-danger/20 bg-danger/10 p-3 text-base font-semibold text-danger">
                    {error}
                  </div>
                ) : null}
              </FieldGroup>

              <DialogFooter className="-mx-6 -mb-6 mt-2 border-t border-black/5 bg-slate-100/50 px-6 py-3.5 sm:justify-end gap-2 dark:border-white/10 dark:bg-zinc-800/40">
                <DialogClose asChild>
                  <Button
                    type="button"
                    variant="outline"
                    className="h-9 rounded-xl border-slate-200 px-4 text-base font-semibold"
                  >
                    {t("cancel")}
                  </Button>
                </DialogClose>
                <Button
                  type="submit"
                  variant="skew"
                  className="h-9 px-5 text-base font-semibold tracking-wide"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? t("submitting") : t("submit")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

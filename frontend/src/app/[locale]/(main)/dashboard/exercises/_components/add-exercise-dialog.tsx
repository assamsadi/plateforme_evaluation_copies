"use client";

import { type FormEvent, useEffect, useState } from "react";

import { BookPlus, Info, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import { listModulesByProgram, listPrograms, type ModuleRead, type ProgramRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { createExercise, type ExerciseRead } from "@/lib/professor-api";

import {
  formCancelBtnCn,
  formErrorCn,
  formInputCn,
  formLabelCn,
  formSelectTriggerCn,
  formSubmitBtnCn,
  formTextareaCn,
} from "../../_components/form-styles";

export function AddExerciseDialog({ onCreated }: { onCreated: (exercise: ExerciseRead) => void }) {
  const t = useTranslations("AddExerciseDialog");
  const [open, setOpen] = useState(false);

  const [programs, setPrograms] = useState<ProgramRead[]>([]);
  const [modules, setModules] = useState<ModuleRead[]>([]);
  const [programId, setProgramId] = useState("");
  const [moduleId, setModuleId] = useState("");

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function resetAndClose() {
    setProgramId("");
    setModuleId("");
    setModules([]);
    setTitle("");
    setDescription("");
    setError(null);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const session = getStoredSession();
    if (!session) return;
    listPrograms(session.accessToken)
      .then((page) => setPrograms(page.items))
      .catch(() => setPrograms([]));
  }, [open]);

  useEffect(() => {
    setModuleId("");
    setModules([]);
    if (!programId) return;
    const session = getStoredSession();
    if (!session) return;
    listModulesByProgram(session.accessToken, programId)
      .then((page) => setModules(page.items))
      .catch(() => setModules([]));
  }, [programId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const created = await createExercise(session.accessToken, {
        module_id: moduleId,
        title,
        description: description || null,
        questions: [],
      });
      onCreated(created);
      resetAndClose();
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  const canSubmit = Boolean(moduleId && title.trim());

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) resetAndClose();
        else setOpen(true);
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="skew" className="h-10 px-4 text-base font-semibold tracking-wide">
          <Plus className="size-3.5" /> {t("trigger")}
        </Button>
      </DialogTrigger>
      <TrafficLightDialog
        open={open}
        onOpenChange={(next) => {
          if (!next) resetAndClose();
          else setOpen(true);
        }}
        contentClassName="sm:max-w-lg"
        footer={
          <>
            <DialogClose asChild>
              <Button type="button" variant="outline" className={formCancelBtnCn}>
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button
              type="submit"
              form="add-exercise-form"
              disabled={isSubmitting || !canSubmit}
              className={formSubmitBtnCn}
            >
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </>
        }
      >
        <>
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <BookPlus className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-lg font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-500 dark:text-zinc-400">{t("descriptionField")}</p>
              </div>
            </div>
          </DialogHeader>

          <div className="mt-4 flex items-start gap-2.5 rounded-lg border border-info/20 bg-info/10 p-3 text-sm leading-relaxed text-info">
            <Info className="mt-0.5 size-4 shrink-0 text-info" />
            <span>{t("uploadHint")}</span>
          </div>

          <form id="add-exercise-form" onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
            <FieldGroup className="gap-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Field className="gap-2">
                  <FieldLabel htmlFor="add-exercise-program" className={formLabelCn}>
                    {t("program")}
                  </FieldLabel>
                  <Select value={programId} onValueChange={setProgramId}>
                    <SelectTrigger id="add-exercise-program" className={formSelectTriggerCn}>
                      <SelectValue placeholder={t("programPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {programs.map((program) => (
                        <SelectItem key={program.id} value={program.id} className="text-sm font-medium">
                          {program.name} ({program.code})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field className="gap-2">
                  <FieldLabel htmlFor="add-exercise-module" className={formLabelCn}>
                    {t("module")}
                  </FieldLabel>
                  <Select value={moduleId} onValueChange={setModuleId} disabled={!programId}>
                    <SelectTrigger id="add-exercise-module" className={formSelectTriggerCn}>
                      <SelectValue placeholder={t("modulePlaceholder")} />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {modules.map((module) => (
                        <SelectItem key={module.id} value={module.id} className="text-sm font-medium">
                          {module.name} ({module.code})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              </div>

              <Field className="gap-2">
                <FieldLabel htmlFor="add-exercise-title" className={formLabelCn}>
                  {t("titleField")}
                </FieldLabel>
                <Input
                  id="add-exercise-title"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  className={formInputCn}
                  required
                />
              </Field>

              <Field className="gap-2">
                <FieldLabel htmlFor="add-exercise-description" className={formLabelCn}>
                  {t("descriptionField")}
                </FieldLabel>
                <Textarea
                  id="add-exercise-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  rows={3}
                  className={formTextareaCn}
                />
              </Field>

              {error ? <div className={formErrorCn}>{error}</div> : null}
            </FieldGroup>
          </form>
        </>
      </TrafficLightDialog>
    </Dialog>
  );
}

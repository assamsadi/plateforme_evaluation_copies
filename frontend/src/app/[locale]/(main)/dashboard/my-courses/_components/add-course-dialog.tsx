"use client";

import { type FormEvent, useEffect, useState } from "react";

import { GraduationCap, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  listGroupsByProgram,
  listModulesByProgram,
  listPrograms,
  type GroupRead,
  type ModuleRead,
  type ProgramRead,
} from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { createCourse, type CourseRead } from "@/lib/professor-api";

export function AddCourseDialog({ onCreated }: { onCreated: (course: CourseRead) => void }) {
  const t = useTranslations("AddCourseDialog");
  const [open, setOpen] = useState(false);

  const [programs, setPrograms] = useState<ProgramRead[]>([]);
  const [modules, setModules] = useState<ModuleRead[]>([]);
  const [groups, setGroups] = useState<GroupRead[]>([]);

  const [programId, setProgramId] = useState("");
  const [moduleId, setModuleId] = useState("");
  const [groupId, setGroupId] = useState("");
  const [semester, setSemester] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function resetAndClose() {
    setProgramId("");
    setModuleId("");
    setGroupId("");
    setSemester("");
    setModules([]);
    setGroups([]);
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
    setGroupId("");
    setModules([]);
    setGroups([]);
    if (!programId) return;

    const session = getStoredSession();
    if (!session) return;
    listModulesByProgram(session.accessToken, programId)
      .then((page) => setModules(page.items))
      .catch(() => setModules([]));
    listGroupsByProgram(session.accessToken, programId)
      .then((page) => setGroups(page.items))
      .catch(() => setGroups([]));
  }, [programId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const created = await createCourse(session.accessToken, {
        module_id: moduleId,
        group_id: groupId,
        semester,
      });
      onCreated(created);
      resetAndClose();
    } catch (submitError) {
      console.error("createCourse failed", submitError);
      const message =
        submitError instanceof AuthApiError
          ? submitError.message
          : submitError instanceof Error
            ? `${t("genericError")} (${submitError.message})`
            : t("genericError");
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }

  const canSubmit = Boolean(moduleId && groupId && semester);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) resetAndClose();
        else setOpen(true);
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="skew" className="h-10 px-4 text-sm font-semibold tracking-wide">
          <Plus className="size-3.5" /> {t("trigger")}
        </Button>
      </DialogTrigger>
      <DialogContent className="overflow-hidden p-0 sm:max-w-md">
        <div className="h-1.5 w-full bg-primary" />
        
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <GraduationCap className="size-4" />
              </div>
              <div>
                <DialogTitle className="text-base font-semibold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">{t("semester")}</p>
              </div>
            </div>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
            <FieldGroup className="gap-4">
              <Field className="gap-1.5">
                <FieldLabel htmlFor="add-course-program" className="text-xs font-semibold">
                  {t("program")}
                </FieldLabel>
                <Select value={programId} onValueChange={setProgramId}>
                  <SelectTrigger id="add-course-program" className="h-9 w-full">
                    <SelectValue placeholder={t("programPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    {programs.map((program) => (
                      <SelectItem key={program.id} value={program.id} className="text-xs">
                        {program.name} ({program.code})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              <Field className="gap-1.5">
                <FieldLabel htmlFor="add-course-module" className="text-xs font-semibold">
                  {t("module")}
                </FieldLabel>
                <Select value={moduleId} onValueChange={setModuleId} disabled={!programId}>
                  <SelectTrigger id="add-course-module" className="h-9 w-full">
                    <SelectValue placeholder={t("modulePlaceholder")} />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    {modules.map((module) => (
                      <SelectItem key={module.id} value={module.id} className="text-xs">
                        {module.name} ({module.code})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              <Field className="gap-1.5">
                <FieldLabel htmlFor="add-course-group" className="text-xs font-semibold">
                  {t("group")}
                </FieldLabel>
                <Select value={groupId} onValueChange={setGroupId} disabled={!programId}>
                  <SelectTrigger id="add-course-group" className="h-9 w-full">
                    <SelectValue placeholder={t("groupPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    {groups.map((group) => (
                      <SelectItem key={group.id} value={group.id} className="text-xs">
                        {group.label} ({group.academic_year})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              <Field className="gap-1.5">
                <FieldLabel htmlFor="add-course-semester" className="text-xs font-semibold">
                  {t("semester")}
                </FieldLabel>
                <Input
                  id="add-course-semester"
                  value={semester}
                  onChange={(event) => setSemester(event.target.value)}
                  placeholder={t("semesterPlaceholder")}
                  className="h-9"
                  required
                />
              </Field>

              {error ? (
                <div className="rounded-lg border border-danger/20 bg-danger/10 px-3.5 py-2.5 text-xs font-medium text-danger">
                  {error}
                </div>
              ) : null}
            </FieldGroup>

            <DialogFooter className="mt-2 -mx-6 -mb-6 rounded-b-xl border-t bg-muted/50 p-4 sm:justify-end">
              <DialogClose asChild>
                <Button type="button" variant="outline" className="h-9">
                  {t("cancel")}
                </Button>
              </DialogClose>
              <Button
                type="submit"
                disabled={isSubmitting || !canSubmit}
                className="h-9 px-4"
              >
                {isSubmitting ? t("submitting") : t("submit")}
              </Button>
            </DialogFooter>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { type FormEvent, useState } from "react";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { createGroup, type GroupRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

const emptyFields = { label: "", academicYear: "" };

const ACADEMIC_YEAR_PATTERN = /^(\d{4})-(\d{4})$/;

function isValidAcademicYear(value: string): boolean {
  const match = ACADEMIC_YEAR_PATTERN.exec(value);
  if (!match) return false;
  return Number(match[2]) === Number(match[1]) + 1;
}

export function AddGroupDialog({ programId, onCreated }: { programId: string; onCreated: (group: GroupRead) => void }) {
  const t = useTranslations("AddGroupDialog");
  const [open, setOpen] = useState(false);
  const [fields, setFields] = useState(emptyFields);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function updateField(key: keyof typeof emptyFields, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  function resetAndClose() {
    setFields(emptyFields);
    setError(null);
    setOpen(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!isValidAcademicYear(fields.academicYear)) {
      setError(t("academicYearInvalid"));
      return;
    }

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const created = await createGroup(session.accessToken, programId, {
        program_id: programId,
        label: fields.label,
        academic_year: fields.academicYear,
      });
      onCreated(created);
      resetAndClose();
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

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
          <Plus className="size-4" /> {t("trigger")}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FieldGroup className="gap-4">
            <Field className="gap-1.5">
              <FieldLabel htmlFor="add-group-label">{t("label")}</FieldLabel>
              <Input
                id="add-group-label"
                value={fields.label}
                onChange={(event) => updateField("label", event.target.value)}
                required
              />
            </Field>
            <Field className="gap-1.5">
              <FieldLabel htmlFor="add-group-academic-year">{t("academicYear")}</FieldLabel>
              <Input
                id="add-group-academic-year"
                placeholder="2025-2026"
                value={fields.academicYear}
                onChange={(event) => updateField("academicYear", event.target.value)}
                required
              />
              <FieldDescription>{t("academicYearHint")}</FieldDescription>
            </Field>

            {error ? <p className="text-destructive text-base">{error}</p> : null}
          </FieldGroup>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

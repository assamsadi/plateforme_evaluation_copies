"use client";

import { type FormEvent, useEffect, useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { type ModuleRead, updateModule } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

export function EditModuleDialog({
  module: moduleToEdit,
  open,
  onOpenChange,
  onUpdated,
}: {
  module: ModuleRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (module_: ModuleRead) => void;
}) {
  const t = useTranslations("EditModuleDialog");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (moduleToEdit) {
      setName(moduleToEdit.name);
      setCode(moduleToEdit.code);
      setError(null);
    }
  }, [moduleToEdit]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !moduleToEdit) return;

    setIsSubmitting(true);
    try {
      const updated = await updateModule(session.accessToken, moduleToEdit.id, { name, code });
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
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FieldGroup className="gap-4">
            <Field className="gap-1.5">
              <FieldLabel htmlFor="edit-module-name">{t("name")}</FieldLabel>
              <Input id="edit-module-name" value={name} onChange={(event) => setName(event.target.value)} required />
            </Field>
            <Field className="gap-1.5">
              <FieldLabel htmlFor="edit-module-code">{t("code")}</FieldLabel>
              <Input id="edit-module-code" value={code} onChange={(event) => setCode(event.target.value)} required />
              <FieldDescription>{t("codeHint")}</FieldDescription>
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

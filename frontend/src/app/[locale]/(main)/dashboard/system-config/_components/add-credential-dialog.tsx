"use client";

import { type FormEvent, useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { createProviderCredential, type ProviderCredentialRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

// Suggestions courantes — PAS une liste fermée côté backend (l'admin
// choisit lui-même le fournisseur, cf. plan validé) : juste un raccourci
// pratique, "Autre" révèle un champ nom libre pour n'importe quelle clé.
const SUGGESTED_KEYS = [
  "GROQ_API_KEY",
  "OPENAI_API_KEY",
  "GOOGLE_API_KEY",
  "OPENROUTER_API_KEY",
  "ANTHROPIC_API_KEY",
  "MISTRAL_API_KEY",
  "LANGFUSE_SECRET_KEY",
  "LANGFUSE_PUBLIC_KEY",
  "LANGFUSE_BASE_URL",
] as const;
const CUSTOM_OPTION = "__custom__";

export function AddCredentialDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (credential: ProviderCredentialRead) => void;
}) {
  const t = useTranslations("AddCredentialDialog");
  const [selected, setSelected] = useState<string>(SUGGESTED_KEYS[0]);
  const [customKey, setCustomKey] = useState("");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isCustom = selected === CUSTOM_OPTION;
  const effectiveKey = isCustom ? customKey.trim() : selected;

  function reset() {
    setSelected(SUGGESTED_KEYS[0]);
    setCustomKey("");
    setValue("");
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !effectiveKey) return;

    setIsSubmitting(true);
    try {
      const created = await createProviderCredential(session.accessToken, effectiveKey, value);
      onCreated(created);
      reset();
      onOpenChange(false);
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
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FieldGroup className="gap-4">
            <Field className="gap-1.5">
              <FieldLabel htmlFor="add-credential-select">{t("provider")}</FieldLabel>
              <Select value={selected} onValueChange={setSelected}>
                <SelectTrigger id="add-credential-select" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SUGGESTED_KEYS.map((key) => (
                    <SelectItem key={key} value={key} className="font-mono text-sm">
                      {key}
                    </SelectItem>
                  ))}
                  <SelectItem value={CUSTOM_OPTION}>{t("customOption")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            {isCustom ? (
              <Field className="gap-1.5">
                <FieldLabel htmlFor="add-credential-custom-key">{t("customKeyLabel")}</FieldLabel>
                <Input
                  id="add-credential-custom-key"
                  value={customKey}
                  onChange={(event) => setCustomKey(event.target.value)}
                  placeholder={t("customKeyPlaceholder")}
                  required
                />
                <FieldDescription>{t("customKeyHint")}</FieldDescription>
              </Field>
            ) : null}

            <Field className="gap-1.5">
              <FieldLabel htmlFor="add-credential-value">{t("value")}</FieldLabel>
              <Input
                id="add-credential-value"
                type="password"
                autoComplete="off"
                value={value}
                onChange={(event) => setValue(event.target.value)}
                placeholder={t("valuePlaceholder")}
                required
              />
            </Field>

            {error ? <p className="text-destructive text-base">{error}</p> : null}
          </FieldGroup>

          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" disabled={isSubmitting || !effectiveKey}>
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

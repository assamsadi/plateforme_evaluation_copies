"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Info, KeyRound, Lock, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { StatusBadge } from "@/components/ui/status-badge";
import { type ProviderCredentialRead, updateProviderCredential } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

function CredentialKeyTooltip({ credKey }: { credKey: string }) {
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
          <p className="font-semibold text-slate-500 dark:text-zinc-400">Identifiant API :</p>
          <p className="select-all text-emerald-600 dark:text-emerald-400">{credKey}</p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function EditCredentialDialog({
  credential,
  open,
  onOpenChange,
  onUpdated,
}: {
  credential: ProviderCredentialRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (credential: ProviderCredentialRead) => void;
}) {
  const t = useTranslations("EditCredentialDialog");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (credential) {
      setValue("");
      setError(null);
    }
  }, [credential]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !credential) return;

    setIsSubmitting(true);
    try {
      const updated = await updateProviderCredential(session.accessToken, credential.key, value);
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
          <span className="font-mono text-sm font-semibold text-slate-500 dark:text-zinc-400">
            {credential ? credential.key : "provider-credential"}
          </span>
        </div>

        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3.5">
                <div className="flex size-13 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary font-bold text-xl shadow-2xs">
                  <KeyRound className="size-6" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <DialogTitle className="text-xl font-bold text-slate-900 dark:text-zinc-100">
                      {credential ? credential.key : t("title")}
                    </DialogTitle>
                    {credential ? <CredentialKeyTooltip credKey={credential.key} /> : null}
                  </div>
                  <p className="text-base font-medium text-muted-foreground">Clé API et secret fournisseur LLM</p>
                </div>
              </div>

              {credential ? (
                <StatusBadge
                  tone={credential.source === "database" ? "success" : "neutral"}
                  status={credential.source}
                />
              ) : null}
            </div>
          </DialogHeader>

          {credential ? (
            <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              {/* Informations Contexte */}
              <div className="rounded-xl border border-black/5 bg-white/80 p-4 shadow-2xs dark:border-white/5 dark:bg-zinc-800/50">
                <div className="flex items-center gap-2 mb-2 pb-2 border-b border-black/5 dark:border-white/5">
                  <Sparkles className="size-4 text-primary" />
                  <span className="text-sm font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                    État du secret
                  </span>
                </div>
                <div className="flex items-center justify-between gap-4 py-1.5 border-b border-black/5 last:border-0 dark:border-white/5">
                  <span className="text-base font-medium text-slate-600 dark:text-zinc-400">Source actuelle</span>
                  <span className="font-mono text-base font-semibold text-slate-900 dark:text-zinc-100">
                    {credential.source}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-4 py-1.5 border-b border-black/5 last:border-0 dark:border-white/5">
                  <span className="text-base font-medium text-slate-600 dark:text-zinc-400">Actif dans le graphe</span>
                  <span className="text-base font-semibold text-emerald-600 dark:text-emerald-400">
                    {credential.is_wired ? "Oui (Connecté)" : "Non"}
                  </span>
                </div>
              </div>

              {/* Champ d'édition */}
              <FieldGroup className="gap-2">
                <Field className="gap-2">
                  <FieldLabel
                    htmlFor="edit-credential-value"
                    className="text-base font-semibold text-slate-800 dark:text-zinc-200"
                  >
                    <span className="flex items-center gap-1.5">
                      <Lock className="size-3.5 text-slate-500" />
                      {t("value")} (Nouvelle clé secrète)
                    </span>
                  </FieldLabel>
                  <Input
                    id="edit-credential-value"
                    type="password"
                    autoComplete="off"
                    value={value}
                    onChange={(event) => setValue(event.target.value)}
                    placeholder={t("valuePlaceholder")}
                    required
                    className="h-10 rounded-xl border-slate-200 bg-white font-mono text-base dark:border-zinc-700 dark:bg-zinc-800"
                  />
                  <FieldDescription className="text-sm text-muted-foreground">{t("hint")}</FieldDescription>
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

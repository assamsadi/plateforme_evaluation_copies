"use client";

import { useState } from "react";

import { ArrowLeft, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { DeleteConfirmDialog } from "@/app/[locale]/(main)/dashboard/_components/delete-confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Link, useRouter } from "@/i18n/navigation";
import { deleteProgram, type ProgramRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

export function ProgramHeader({ program }: { program: ProgramRead }) {
  const t = useTranslations("ProgramDetail");
  const router = useRouter();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  async function handleDelete() {
    const session = getStoredSession();
    if (!session) return;

    setIsDeleting(true);
    try {
      await deleteProgram(session.accessToken, program.id);
      toast.success(t("deleteSuccess", { name: program.name }));
      router.push("/dashboard/programs");
    } catch (error) {
      toast.error(error instanceof AuthApiError ? error.message : t("deleteError"));
    } finally {
      setIsDeleting(false);
      setConfirmOpen(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/dashboard/programs"
        className="flex w-fit items-center gap-1.5 text-muted-foreground text-base hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" />
        {t("back")}
      </Link>
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="font-semibold text-2xl">{program.name}</h1>
          <Badge className="font-mono" variant="outline">
            {program.code}
          </Badge>
        </div>
        <Button
          variant="skew-destructive"
          size="sm"
          className="h-9 px-4 text-base font-semibold tracking-wide"
          onClick={() => setConfirmOpen(true)}
        >
          <Trash2 className="size-4" />
          {t("deleteProgram")}
        </Button>
      </div>

      <DeleteConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={t("deleteProgram")}
        description={t("deleteConfirmDescription", { name: program.name })}
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteProgram")}
        isPending={isDeleting}
        onConfirm={handleDelete}
      />
    </div>
  );
}

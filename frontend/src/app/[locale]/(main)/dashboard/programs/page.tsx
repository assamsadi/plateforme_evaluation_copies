"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DataTableSkeleton } from "@/app/[locale]/(main)/dashboard/_components/data-table-skeleton";
import { DeleteConfirmDialog } from "@/app/[locale]/(main)/dashboard/_components/delete-confirm-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { deleteProgram, listPrograms, type ProgramRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { EditProgramDialog } from "./_components/edit-program-dialog";
import { Programs } from "./_components/programs";
import type { ProgramRow } from "./_components/data";

const PAGE_SIZE = 200;

function toProgramRow(program: ProgramRead): ProgramRow {
  return { id: program.id, name: program.name, code: program.code };
}

function ProgramsPageContent() {
  const t = useTranslations("Programs");
  const [programs, setPrograms] = useState<ProgramRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingProgramId, setPendingProgramId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ProgramRow | null>(null);
  const [editTarget, setEditTarget] = useState<ProgramRow | null>(null);

  const fetchPrograms = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listPrograms(session.accessToken);
      setPrograms(page.items.map(toProgramRow));
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchPrograms();
  }, [fetchPrograms]);

  async function handleConfirmDelete() {
    const session = getStoredSession();
    const target = deleteTarget;
    if (!session || !target) return;

    setPendingProgramId(target.id);
    try {
      await deleteProgram(session.accessToken, target.id);
      setPrograms((prev) => prev.filter((p) => p.id !== target.id));
      toast.success(t("deleteSuccess", { name: target.name }));
      setDeleteTarget(null);
    } catch (actionError) {
      toast.error(actionError instanceof AuthApiError ? actionError.message : t("deleteError"));
    } finally {
      setPendingProgramId(null);
    }
  }

  function handleCreated(created: ProgramRead) {
    setPrograms((prev) => [toProgramRow(created), ...prev]);
    toast.success(t("createSuccess", { name: created.name }));
  }

  function handleUpdated(updated: ProgramRead) {
    setPrograms((prev) => prev.map((p) => (p.id === updated.id ? toProgramRow(updated) : p)));
    toast.success(t("updateSuccess", { name: updated.name }));
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading) {
    return <DataTableSkeleton columnCount={3} />;
  }

  return (
    <>
      <Programs
        programs={programs}
        onEdit={setEditTarget}
        onDelete={setDeleteTarget}
        onCreated={handleCreated}
        pendingProgramId={pendingProgramId}
      />
      <EditProgramDialog
        program={editTarget}
        open={Boolean(editTarget)}
        onOpenChange={(open) => !open && setEditTarget(null)}
        onUpdated={handleUpdated}
      />
      <DeleteConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={t("deleteConfirmTitle")}
        description={deleteTarget ? t("deleteConfirmDescription", { name: deleteTarget.name }) : ""}
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteAction")}
        isPending={Boolean(pendingProgramId)}
        onConfirm={handleConfirmDelete}
      />
    </>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <ProgramsPageContent />
    </AuthGuard>
  );
}

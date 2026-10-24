"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DataTableSkeleton } from "@/app/[locale]/(main)/dashboard/_components/data-table-skeleton";
import { DeleteConfirmDialog } from "@/app/[locale]/(main)/dashboard/_components/delete-confirm-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { deactivateUser, listUsers, reactivateUser } from "@/lib/admin-api";
import { AuthApiError, getStoredSession, type UserPublic } from "@/lib/auth-api";
import { useAuth } from "@/lib/auth-context";

import type { UserRow } from "./_components/data";
import { EditUserDialog } from "./_components/edit-user-dialog";
import { UserDetailDialog } from "./_components/user-detail-dialog";
import { Users } from "./_components/users";

// GET /admin/users est paginé par curseur côté backend (max 200/page) ; on
// charge la première grande page plutôt que d'implémenter le curseur "load
// more" ici — suffisant pour un volume d'utilisateurs admin typique, mais
// une vraie pagination serveur serait nécessaire au-delà de 200 comptes.
const PAGE_SIZE = 200;

function toUserRow(user: UserPublic): UserRow {
  return {
    id: user.id,
    email: user.email,
    firstName: user.first_name,
    lastName: user.last_name,
    role: user.role as UserRow["role"],
    isActive: user.is_active,
  };
}

function UsersPageContent() {
  const t = useTranslations("Users");
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingUserId, setPendingUserId] = useState<string | null>(null);
  const [viewTarget, setViewTarget] = useState<UserRow | null>(null);
  const [editTarget, setEditTarget] = useState<UserRow | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<UserRow | null>(null);

  const fetchUsers = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listUsers(session.accessToken, { limit: PAGE_SIZE });
      setUsers(page.items.map(toUserRow));
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  function requestDeactivate(target: UserRow) {
    if (currentUser && target.id === currentUser.id) {
      toast.error(t("deactivateSelfError"));
      return;
    }
    setDeactivateTarget(target);
  }

  async function handleConfirmDeactivate() {
    const session = getStoredSession();
    const target = deactivateTarget;
    if (!session || !target) return;

    setPendingUserId(target.id);
    try {
      const updated = await deactivateUser(session.accessToken, target.id);
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? toUserRow(updated) : u)));
      toast.success(t("deactivateSuccess", { name: `${target.firstName} ${target.lastName}` }));
      setDeactivateTarget(null);
    } catch (actionError) {
      toast.error(actionError instanceof AuthApiError ? actionError.message : t("deactivateError"));
    } finally {
      setPendingUserId(null);
    }
  }

  async function handleReactivate(target: UserRow) {
    const session = getStoredSession();
    if (!session) return;

    setPendingUserId(target.id);
    try {
      const updated = await reactivateUser(session.accessToken, target.id);
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? toUserRow(updated) : u)));
      toast.success(t("reactivateSuccess", { name: `${target.firstName} ${target.lastName}` }));
    } catch (actionError) {
      toast.error(actionError instanceof AuthApiError ? actionError.message : t("reactivateError"));
    } finally {
      setPendingUserId(null);
    }
  }

  function handleCreated(created: UserPublic) {
    setUsers((prev) => [toUserRow(created), ...prev]);
    toast.success(t("createSuccess", { name: `${created.first_name} ${created.last_name}` }));
  }

  function handleUpdated(updated: UserPublic) {
    setUsers((prev) => prev.map((u) => (u.id === updated.id ? toUserRow(updated) : u)));
    toast.success(t("updateSuccess", { name: `${updated.first_name} ${updated.last_name}` }));
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
    return <DataTableSkeleton columnCount={4} />;
  }

  return (
    <>
      <Users
        users={users}
        onView={setViewTarget}
        onEdit={setEditTarget}
        onDeactivate={requestDeactivate}
        onReactivate={handleReactivate}
        onCreated={handleCreated}
        pendingUserId={pendingUserId}
      />
      <UserDetailDialog
        user={viewTarget}
        open={Boolean(viewTarget)}
        onOpenChange={(open) => !open && setViewTarget(null)}
      />
      <EditUserDialog
        user={editTarget}
        open={Boolean(editTarget)}
        onOpenChange={(open) => !open && setEditTarget(null)}
        onUpdated={handleUpdated}
      />
      <DeleteConfirmDialog
        open={Boolean(deactivateTarget)}
        onOpenChange={(open) => !open && setDeactivateTarget(null)}
        title={t("deactivateAction")}
        description={
          deactivateTarget
            ? t("deactivateConfirmDescription", { name: `${deactivateTarget.firstName} ${deactivateTarget.lastName}` })
            : ""
        }
        cancelLabel={t("cancel")}
        confirmLabel={t("deactivateAction")}
        isPending={Boolean(pendingUserId)}
        onConfirm={handleConfirmDeactivate}
      />
    </>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <UsersPageContent />
    </AuthGuard>
  );
}

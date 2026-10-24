"use client";

import { useEffect, useState } from "react";

import { Building2, Calendar, GraduationCap, Info, Mail, MapPin, ShieldCheck, User } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { StatusBadge } from "@/components/ui/status-badge";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import { getUserDetail, type UserDetail } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import type { UserRow } from "./data";

function isProfessorDetail(detail: UserDetail): boolean {
  return detail.role === "professor";
}

function isStudentDetail(detail: UserDetail): boolean {
  return detail.role === "student";
}

function roleLabel(role: string, t: (key: string) => string): string {
  if (role === "student") return t("roleStudent");
  if (role === "professor") return t("roleProfessor");
  return t("roleAdmin");
}

function UserIdTooltip({ userId }: { userId: string }) {
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
      <PopoverContent className="w-[34rem] max-w-[95vw] gap-0 overflow-hidden rounded-xl border-0 bg-[#F8FBFE] p-0 shadow-xl ring-1 ring-black/5 dark:bg-zinc-900 dark:ring-white/10">
        <div className="flex items-center gap-2 px-5 py-3.5">
          <span className="size-3.5 rounded-full bg-[#ff605c]" />
          <span className="size-3.5 rounded-full bg-[#ffbd44]" />
          <span className="size-3.5 rounded-full bg-[#00ca4e]" />
        </div>
        <div className="flex flex-col gap-1.5 border-t border-black/5 px-5 py-5 text-left dark:border-white/10">
          <span className="text-base font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
            UUID Système
          </span>
          <span className="select-all font-mono text-base font-medium break-all text-black dark:text-white">
            {userId}
          </span>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function InfoItem({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-slate-100 last:border-0 dark:border-zinc-800/60">
      <div className="flex items-center gap-2.5 text-muted-foreground">
        <Icon className="size-4.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
        <span className="text-base font-semibold text-slate-700 dark:text-zinc-300">{label}</span>
      </div>
      <span className="text-base font-bold text-black dark:text-white text-right">{value}</span>
    </div>
  );
}

export function UserDetailDialog({
  user,
  open,
  onOpenChange,
}: {
  user: UserRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("UserDetailDialog");
  const usersT = useTranslations("Users");
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !user) return;
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    setDetail(null);
    getUserDetail(session.accessToken, user.id)
      .then(setDetail)
      .catch((fetchError) => {
        setError(fetchError instanceof AuthApiError ? fetchError.message : t("genericError"));
      })
      .finally(() => setIsLoading(false));
  }, [open, user, t]);

  return (
    <TrafficLightDialog
      open={open}
      onOpenChange={onOpenChange}
      contentClassName="sm:max-w-2xl"
      footer={
        <DialogClose asChild>
          <Button variant="skew" size="sm" className="h-9 px-5 text-base font-semibold">
            Fermer
          </Button>
        </DialogClose>
      }
    >
      <>
        <DialogHeader className="gap-2">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3.5">
              <div className="flex size-13 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary font-bold text-xl shadow-2xs">
                {detail ? (
                  `${detail.first_name[0] || ""}${detail.last_name[0] || ""}`.toUpperCase()
                ) : (
                  <User className="size-6" />
                )}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <DialogTitle className="text-xl font-bold text-slate-900 dark:text-zinc-100">
                    {detail
                      ? `${detail.first_name} ${detail.last_name}`
                      : user
                        ? `${user.firstName} ${user.lastName}`
                        : t("title")}
                  </DialogTitle>
                  {user ? <UserIdTooltip userId={user.id} /> : null}
                </div>
                <p className="text-base font-medium text-muted-foreground">{detail?.email ?? user?.email}</p>
              </div>
            </div>

            {detail ? (
              <div className="flex items-center gap-1.5">
                <StatusBadge
                  tone={detail.is_active ? "success" : "danger"}
                  status={detail.is_active ? usersT("statusActive") : usersT("statusDeactivated")}
                />
                <StatusBadge tone="neutral" status={roleLabel(detail.role, usersT)} />
              </div>
            ) : null}
          </div>
        </DialogHeader>

        {isLoading ? (
          <div className="flex h-40 items-center justify-center">
            <p className="text-muted-foreground text-base font-medium animate-pulse">{t("loading")}</p>
          </div>
        ) : error ? (
          <div className="mt-4 rounded-xl border border-danger/20 bg-danger/10 p-4 text-base font-semibold text-danger">
            {error}
          </div>
        ) : detail ? (
          <div className="mt-5 flex flex-col gap-4">
            {/* Section Informations Générales */}
            <div className="rounded-xl border border-black/5 bg-white/80 p-4 shadow-2xs dark:border-white/5 dark:bg-zinc-800/50">
              <div className="flex items-center gap-2 mb-2 pb-2 border-b border-black/5 dark:border-white/5">
                <User className="size-4 text-primary" />
                <span className="text-base font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  Identité
                </span>
              </div>
              <InfoItem icon={User} label={t("firstName")} value={detail.first_name} />
              <InfoItem icon={User} label={t("lastName")} value={detail.last_name} />
              <InfoItem icon={Mail} label={t("email")} value={detail.email} />
            </div>

            {/* Section Spécifique Professeur */}
            {isProfessorDetail(detail) && "department" in detail ? (
              <div className="rounded-xl border border-black/5 bg-white/80 p-4 shadow-2xs dark:border-white/5 dark:bg-zinc-800/50">
                <div className="flex items-center gap-2 mb-2 pb-2 border-b border-black/5 dark:border-white/5">
                  <Building2 className="size-4 text-primary" />
                  <span className="text-base font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                    Poste & Département
                  </span>
                </div>
                <InfoItem icon={Building2} label={t("department")} value={detail.department} />
                <InfoItem icon={ShieldCheck} label={t("professorTitle")} value={detail.title} />
                <InfoItem icon={Info} label={t("employeeNumber")} value={detail.employee_number} />
                {detail.office_location ? (
                  <InfoItem icon={MapPin} label={t("officeLocation")} value={detail.office_location} />
                ) : null}
                {detail.specialty ? (
                  <InfoItem icon={GraduationCap} label={t("specialty")} value={detail.specialty} />
                ) : null}
              </div>
            ) : null}

            {isStudentDetail(detail) && "student_number" in detail ? (
              <div className="rounded-xl border border-black/5 bg-white/80 p-4 shadow-2xs dark:border-white/5 dark:bg-zinc-800/50">
                <div className="flex items-center gap-2 mb-2 pb-2 border-b border-black/5 dark:border-white/5">
                  <GraduationCap className="size-4 text-primary" />
                  <span className="text-base font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                    Cursus Étudiant
                  </span>
                </div>
                <InfoItem icon={ShieldCheck} label={t("studentNumber")} value={detail.student_number} />
                <InfoItem icon={Calendar} label={t("enrollmentYear")} value={String(detail.enrollment_year)} />
                <InfoItem icon={GraduationCap} label={t("level")} value={detail.level} />
              </div>
            ) : null}
          </div>
        ) : null}
      </>
    </TrafficLightDialog>
  );
}

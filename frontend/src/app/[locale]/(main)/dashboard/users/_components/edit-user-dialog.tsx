"use client";

import { type FormEvent, useEffect, useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  getUserDetail,
  type ProfessorDetail,
  type StudentDetail,
  type UserDetail,
  updateAdmin,
  updateProfessor,
  updateStudent,
} from "@/lib/admin-api";
import { AuthApiError, getStoredSession, type UserPublic } from "@/lib/auth-api";

import type { UserRow } from "./data";

const emptyFields = {
  firstName: "",
  lastName: "",
  email: "",
  department: "",
  title: "",
  employeeNumber: "",
  officeLocation: "",
  specialty: "",
  studentNumber: "",
  groupId: "",
  enrollmentYear: "",
  level: "",
};

function isProfessorDetail(detail: UserDetail): detail is ProfessorDetail {
  return detail.role === "professor";
}

function isStudentDetail(detail: UserDetail): detail is StudentDetail {
  return detail.role === "student";
}

export function EditUserDialog({
  user,
  open,
  onOpenChange,
  onUpdated,
}: {
  user: UserRow | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (user: UserPublic) => void;
}) {
  const t = useTranslations("EditUserDialog");
  const [fields, setFields] = useState(emptyFields);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open || !user) return;
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    getUserDetail(session.accessToken, user.id)
      .then((detail) => {
        setFields({
          firstName: detail.first_name,
          lastName: detail.last_name,
          email: detail.email,
          department: isProfessorDetail(detail) ? detail.department : "",
          title: isProfessorDetail(detail) ? detail.title : "",
          employeeNumber: isProfessorDetail(detail) ? detail.employee_number : "",
          officeLocation: isProfessorDetail(detail) ? (detail.office_location ?? "") : "",
          specialty: isProfessorDetail(detail) ? (detail.specialty ?? "") : "",
          studentNumber: isStudentDetail(detail) ? detail.student_number : "",
          groupId: isStudentDetail(detail) ? detail.group_id : "",
          enrollmentYear: isStudentDetail(detail) ? String(detail.enrollment_year) : "",
          level: isStudentDetail(detail) ? detail.level : "",
        });
      })
      .catch((fetchError) => {
        setError(fetchError instanceof AuthApiError ? fetchError.message : t("genericError"));
      })
      .finally(() => setIsLoading(false));
  }, [open, user, t]);

  function updateField(key: keyof typeof emptyFields, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !user) return;

    const base = {
      email: fields.email,
      first_name: fields.firstName,
      last_name: fields.lastName,
    };

    setIsSubmitting(true);
    try {
      let updated: UserPublic;

      if (user.role === "admin") {
        updated = await updateAdmin(session.accessToken, user.id, base);
      } else if (user.role === "professor") {
        updated = await updateProfessor(session.accessToken, user.id, {
          ...base,
          department: fields.department,
          title: fields.title,
          employee_number: fields.employeeNumber,
          office_location: fields.officeLocation || undefined,
          specialty: fields.specialty || undefined,
        });
      } else {
        updated = await updateStudent(session.accessToken, user.id, {
          ...base,
          student_number: fields.studentNumber,
          group_id: fields.groupId,
          enrollment_year: Number(fields.enrollmentYear),
          level: fields.level,
        });
      }

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

        {isLoading ? (
          <p className="text-muted-foreground text-base">{t("loading")}</p>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <FieldGroup className="gap-4">
              <div className="grid grid-cols-2 gap-3">
                <Field className="gap-1.5">
                  <FieldLabel htmlFor="edit-user-first-name">{t("firstName")}</FieldLabel>
                  <Input
                    id="edit-user-first-name"
                    value={fields.firstName}
                    onChange={(event) => updateField("firstName", event.target.value)}
                    required
                  />
                </Field>
                <Field className="gap-1.5">
                  <FieldLabel htmlFor="edit-user-last-name">{t("lastName")}</FieldLabel>
                  <Input
                    id="edit-user-last-name"
                    value={fields.lastName}
                    onChange={(event) => updateField("lastName", event.target.value)}
                    required
                  />
                </Field>
              </div>

              <Field className="gap-1.5">
                <FieldLabel htmlFor="edit-user-email">{t("email")}</FieldLabel>
                <Input
                  id="edit-user-email"
                  type="email"
                  value={fields.email}
                  onChange={(event) => updateField("email", event.target.value)}
                  required
                />
              </Field>

              {user?.role === "professor" ? (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <Field className="gap-1.5">
                      <FieldLabel htmlFor="edit-user-department">{t("department")}</FieldLabel>
                      <Input
                        id="edit-user-department"
                        value={fields.department}
                        onChange={(event) => updateField("department", event.target.value)}
                        required
                      />
                    </Field>
                    <Field className="gap-1.5">
                      <FieldLabel htmlFor="edit-user-title">{t("professorTitle")}</FieldLabel>
                      <Input
                        id="edit-user-title"
                        value={fields.title}
                        onChange={(event) => updateField("title", event.target.value)}
                        required
                      />
                    </Field>
                  </div>
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="edit-user-employee-number">{t("employeeNumber")}</FieldLabel>
                    <Input
                      id="edit-user-employee-number"
                      value={fields.employeeNumber}
                      onChange={(event) => updateField("employeeNumber", event.target.value)}
                      required
                    />
                  </Field>
                  <div className="grid grid-cols-2 gap-3">
                    <Field className="gap-1.5">
                      <FieldLabel htmlFor="edit-user-office">{t("officeLocation")}</FieldLabel>
                      <Input
                        id="edit-user-office"
                        value={fields.officeLocation}
                        onChange={(event) => updateField("officeLocation", event.target.value)}
                      />
                    </Field>
                    <Field className="gap-1.5">
                      <FieldLabel htmlFor="edit-user-specialty">{t("specialty")}</FieldLabel>
                      <Input
                        id="edit-user-specialty"
                        value={fields.specialty}
                        onChange={(event) => updateField("specialty", event.target.value)}
                      />
                    </Field>
                  </div>
                </>
              ) : null}

              {user?.role === "student" ? (
                <>
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="edit-user-student-number">{t("studentNumber")}</FieldLabel>
                    <Input
                      id="edit-user-student-number"
                      value={fields.studentNumber}
                      onChange={(event) => updateField("studentNumber", event.target.value)}
                      required
                    />
                  </Field>
                  <div className="grid grid-cols-2 gap-3">
                    <Field className="gap-1.5">
                      <FieldLabel htmlFor="edit-user-enrollment-year">{t("enrollmentYear")}</FieldLabel>
                      <Input
                        id="edit-user-enrollment-year"
                        type="number"
                        value={fields.enrollmentYear}
                        onChange={(event) => updateField("enrollmentYear", event.target.value)}
                        required
                      />
                    </Field>
                    <Field className="gap-1.5">
                      <FieldLabel htmlFor="edit-user-level">{t("level")}</FieldLabel>
                      <Input
                        id="edit-user-level"
                        value={fields.level}
                        onChange={(event) => updateField("level", event.target.value)}
                        required
                      />
                    </Field>
                  </div>
                  <p className="text-muted-foreground text-sm">{t("groupNote")}</p>
                </>
              ) : null}

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
        )}
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { type FormEvent, useEffect, useState } from "react";

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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  createAdmin,
  createProfessor,
  createStudent,
  type GroupRead,
  listGroupsByProgram,
  listPrograms,
  type ProgramRead,
} from "@/lib/admin-api";
import { AuthApiError, getStoredSession, type UserPublic } from "@/lib/auth-api";

type Role = "admin" | "professor" | "student";

const emptyFields = {
  firstName: "",
  lastName: "",
  email: "",
  password: "",
  department: "",
  title: "",
  employeeNumber: "",
  officeLocation: "",
  specialty: "",
  studentNumber: "",
  programId: "",
  groupId: "",
  enrollmentYear: "",
  level: "",
};

export function AddUserDialog({ onCreated }: { onCreated: (user: UserPublic) => void }) {
  const t = useTranslations("AddUserDialog");
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<Role>("student");
  const [fields, setFields] = useState(emptyFields);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [programs, setPrograms] = useState<ProgramRead[]>([]);
  const [groups, setGroups] = useState<GroupRead[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(false);

  useEffect(() => {
    if (!open || role !== "student") return;
    const session = getStoredSession();
    if (!session) return;
    listPrograms(session.accessToken)
      .then((page) => setPrograms(page.items))
      .catch(() => setPrograms([]));
  }, [open, role]);

  useEffect(() => {
    if (role !== "student" || !fields.programId) {
      setGroups([]);
      return;
    }
    const session = getStoredSession();
    if (!session) return;
    setIsLoadingGroups(true);
    listGroupsByProgram(session.accessToken, fields.programId)
      .then((page) => setGroups(page.items))
      .catch(() => setGroups([]))
      .finally(() => setIsLoadingGroups(false));
  }, [role, fields.programId]);

  function updateField(key: keyof typeof emptyFields, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }));
  }

  function resetAndClose() {
    setFields(emptyFields);
    setRole("student");
    setError(null);
    setOpen(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    const base = {
      email: fields.email,
      password: fields.password,
      first_name: fields.firstName,
      last_name: fields.lastName,
    };

    setIsSubmitting(true);
    try {
      let created: UserPublic;

      if (role === "admin") {
        created = await createAdmin(session.accessToken, base);
      } else if (role === "professor") {
        created = await createProfessor(session.accessToken, {
          ...base,
          department: fields.department,
          title: fields.title,
          employee_number: fields.employeeNumber,
          office_location: fields.officeLocation || undefined,
          specialty: fields.specialty || undefined,
        });
      } else {
        if (!fields.groupId) {
          setError(t("missingGroup"));
          setIsSubmitting(false);
          return;
        }
        created = await createStudent(session.accessToken, {
          ...base,
          student_number: fields.studentNumber,
          group_id: fields.groupId,
          enrollment_year: Number(fields.enrollmentYear),
          level: fields.level,
        });
      }

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
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FieldGroup className="gap-4">
            <Field className="gap-1.5">
              <FieldLabel htmlFor="add-user-role">{t("role")}</FieldLabel>
              <Select value={role} onValueChange={(value) => setRole(value as Role)}>
                <SelectTrigger id="add-user-role" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="student">{t("roleStudent")}</SelectItem>
                  <SelectItem value="professor">{t("roleProfessor")}</SelectItem>
                  <SelectItem value="admin">{t("roleAdmin")}</SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field className="gap-1.5">
                <FieldLabel htmlFor="add-user-first-name">{t("firstName")}</FieldLabel>
                <Input
                  id="add-user-first-name"
                  value={fields.firstName}
                  onChange={(event) => updateField("firstName", event.target.value)}
                  required
                />
              </Field>
              <Field className="gap-1.5">
                <FieldLabel htmlFor="add-user-last-name">{t("lastName")}</FieldLabel>
                <Input
                  id="add-user-last-name"
                  value={fields.lastName}
                  onChange={(event) => updateField("lastName", event.target.value)}
                  required
                />
              </Field>
            </div>

            <Field className="gap-1.5">
              <FieldLabel htmlFor="add-user-email">{t("email")}</FieldLabel>
              <Input
                id="add-user-email"
                type="email"
                value={fields.email}
                onChange={(event) => updateField("email", event.target.value)}
                required
              />
            </Field>

            <Field className="gap-1.5">
              <FieldLabel htmlFor="add-user-password">{t("password")}</FieldLabel>
              <Input
                id="add-user-password"
                type="password"
                minLength={8}
                placeholder={t("passwordPlaceholder")}
                value={fields.password}
                onChange={(event) => updateField("password", event.target.value)}
                required
              />
            </Field>

            {role === "professor" ? (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-department">{t("department")}</FieldLabel>
                    <Input
                      id="add-user-department"
                      value={fields.department}
                      onChange={(event) => updateField("department", event.target.value)}
                      required
                    />
                  </Field>
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-title">{t("professorTitle")}</FieldLabel>
                    <Input
                      id="add-user-title"
                      value={fields.title}
                      onChange={(event) => updateField("title", event.target.value)}
                      required
                    />
                  </Field>
                </div>
                <Field className="gap-1.5">
                  <FieldLabel htmlFor="add-user-employee-number">{t("employeeNumber")}</FieldLabel>
                  <Input
                    id="add-user-employee-number"
                    value={fields.employeeNumber}
                    onChange={(event) => updateField("employeeNumber", event.target.value)}
                    required
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-office">{t("officeLocation")}</FieldLabel>
                    <Input
                      id="add-user-office"
                      value={fields.officeLocation}
                      onChange={(event) => updateField("officeLocation", event.target.value)}
                    />
                  </Field>
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-specialty">{t("specialty")}</FieldLabel>
                    <Input
                      id="add-user-specialty"
                      value={fields.specialty}
                      onChange={(event) => updateField("specialty", event.target.value)}
                    />
                  </Field>
                </div>
              </>
            ) : null}

            {role === "student" ? (
              <>
                <Field className="gap-1.5">
                  <FieldLabel htmlFor="add-user-student-number">{t("studentNumber")}</FieldLabel>
                  <Input
                    id="add-user-student-number"
                    value={fields.studentNumber}
                    onChange={(event) => updateField("studentNumber", event.target.value)}
                    required
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-program">{t("program")}</FieldLabel>
                    <Select
                      value={fields.programId}
                      onValueChange={(value) => {
                        updateField("programId", value);
                        updateField("groupId", "");
                      }}
                    >
                      <SelectTrigger id="add-user-program" className="w-full">
                        <SelectValue placeholder={t("choose")} />
                      </SelectTrigger>
                      <SelectContent>
                        {programs.map((program) => (
                          <SelectItem key={program.id} value={program.id}>
                            {program.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-group">{t("group")}</FieldLabel>
                    <Select
                      value={fields.groupId}
                      onValueChange={(value) => updateField("groupId", value)}
                      disabled={!fields.programId || isLoadingGroups}
                    >
                      <SelectTrigger id="add-user-group" className="w-full">
                        <SelectValue placeholder={isLoadingGroups ? t("loadingGroups") : t("choose")} />
                      </SelectTrigger>
                      <SelectContent>
                        {groups.map((group) => (
                          <SelectItem key={group.id} value={group.id}>
                            {group.label} ({group.academic_year})
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-enrollment-year">{t("enrollmentYear")}</FieldLabel>
                    <Input
                      id="add-user-enrollment-year"
                      type="number"
                      value={fields.enrollmentYear}
                      onChange={(event) => updateField("enrollmentYear", event.target.value)}
                      required
                    />
                  </Field>
                  <Field className="gap-1.5">
                    <FieldLabel htmlFor="add-user-level">{t("level")}</FieldLabel>
                    <Input
                      id="add-user-level"
                      value={fields.level}
                      onChange={(event) => updateField("level", event.target.value)}
                      required
                    />
                  </Field>
                </div>
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
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { createEnrollment, listUsers, type EnrollmentRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession, type UserPublic } from "@/lib/auth-api";

export function AddEnrollmentForm({
  moduleId,
  onEnrolled,
}: {
  moduleId: string;
  onEnrolled: (enrollment: EnrollmentRead) => void;
}) {
  const t = useTranslations("AddEnrollmentForm");
  const [students, setStudents] = useState<UserPublic[]>([]);
  const [search, setSearch] = useState("");
  const [studentId, setStudentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const session = getStoredSession();
    if (!session) return;
    listUsers(session.accessToken, { role: "student", limit: 200 })
      .then((page) => setStudents(page.items))
      .catch(() => setStudents([]));
  }, []);

  const filteredStudents = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return students;
    return students.filter((student) => {
      const fullName = `${student.first_name} ${student.last_name} ${student.email}`.toLowerCase();
      return fullName.includes(query);
    });
  }, [students, search]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!studentId) {
      setError(t("genericError"));
      return;
    }

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const created = await createEnrollment(session.accessToken, { student_id: studentId, module_id: moduleId });
      onEnrolled(created);
      setStudentId("");
      setSearch("");
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <FieldGroup className="gap-3">
        <Field className="gap-1.5">
          <FieldLabel htmlFor="enroll-student-search">{t("studentLabel")}</FieldLabel>
          <Input
            id="enroll-student-search"
            placeholder={t("searchPlaceholder")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Select value={studentId} onValueChange={setStudentId}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder={t("choose")} />
            </SelectTrigger>
            <SelectContent>
              {filteredStudents.map((student) => (
                <SelectItem key={student.id} value={student.id}>
                  {student.first_name} {student.last_name} — {student.email}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        {error ? <p className="text-destructive text-sm">{error}</p> : null}
      </FieldGroup>

      <Button type="submit" size="sm" disabled={isSubmitting || !studentId}>
        {isSubmitting ? t("submitting") : t("submit")}
      </Button>
    </form>
  );
}

"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { AuthApiError, registerStudent } from "@/lib/auth-api";

const inputClassName =
  "mt-2 block w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-base text-slate-800 placeholder:text-transparent hover:placeholder:text-slate-400 focus:placeholder:text-slate-400 shadow-sm transition-all focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/20 focus:outline-none";
const labelClassName = "block text-sm sm:text-base font-semibold text-slate-700";

export default function SignUpForm() {
  const t = useTranslations("Auth.signUp");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setErrorMessage("");

    const formData = new FormData(event.currentTarget);
    const password = String(formData.get("password"));
    const confirmPassword = String(formData.get("confirmPassword"));

    if (password !== confirmPassword) {
      setStatus("error");
      setErrorMessage(t("passwordMismatch"));
      return;
    }

    try {
      await registerStudent({
        first_name: String(formData.get("firstName")),
        last_name: String(formData.get("lastName")),
        email: String(formData.get("email")),
        password,
        student_number: String(formData.get("studentNumber")),
        enrollment_year: Number(formData.get("enrollmentYear")),
        level: String(formData.get("level")),
        requested_group_label: String(formData.get("group")),
      });
      setStatus("success");
    } catch (error) {
      setStatus("error");
      setErrorMessage(error instanceof AuthApiError ? error.message || t("genericError") : t("networkError"));
    }
  }

  if (status === "success") {
    return (
      <p className="mt-8 rounded-xl bg-emerald-50 p-5 text-center text-base font-semibold text-emerald-700 border border-emerald-200 shadow-sm">
        {t("successMessage")}
      </p>
    );
  }

  return (
    <form className="mt-6 grid grid-cols-1 gap-x-6 gap-y-4 sm:gap-y-5 sm:grid-cols-2" onSubmit={handleSubmit}>
      <div className="group">
        <label htmlFor="firstName" className={labelClassName}>
          {t("firstName")}
        </label>
        <input id="firstName" name="firstName" type="text" placeholder={t("firstNamePlaceholder")} required className={inputClassName} />
      </div>

      <div className="group">
        <label htmlFor="lastName" className={labelClassName}>
          {t("lastName")}
        </label>
        <input id="lastName" name="lastName" type="text" placeholder={t("lastNamePlaceholder")} required className={inputClassName} />
      </div>

      <div className="group">
        <label htmlFor="email" className={labelClassName}>
          {t("email")}
        </label>
        <input id="email" name="email" type="email" placeholder={t("emailPlaceholder")} required className={inputClassName} />
      </div>

      <div className="group">
        <label htmlFor="studentNumber" className={labelClassName}>
          {t("studentNumber")}
        </label>
        <input id="studentNumber" name="studentNumber" type="text" placeholder={t("studentNumberPlaceholder")} required className={inputClassName} />
      </div>

      <div className="group">
        <label htmlFor="enrollmentYear" className={labelClassName}>
          {t("enrollmentYear")}
        </label>
        <input id="enrollmentYear" name="enrollmentYear" type="number" placeholder={t("enrollmentYearPlaceholder")} required className={inputClassName} />
      </div>

      <div className="group">
        <label htmlFor="level" className={labelClassName}>
          {t("level")}
        </label>
        <input id="level" name="level" type="text" placeholder={t("levelPlaceholder")} required className={inputClassName} />
      </div>

      <div className="group sm:col-span-2">
        <label htmlFor="group" className={labelClassName}>
          {t("group")}
        </label>
        <input id="group" name="group" type="text" placeholder={t("groupPlaceholder")} required className={inputClassName} />
      </div>

      <div className="group">
        <label htmlFor="password" className={labelClassName}>
          {t("password")}
        </label>
        <input id="password" name="password" type="password" minLength={8} placeholder={t("passwordPlaceholder")} required className={inputClassName} />
      </div>

      <div className="group">
        <label htmlFor="confirmPassword" className={labelClassName}>
          {t("confirmPassword")}
        </label>
        <input id="confirmPassword" name="confirmPassword" type="password" minLength={8} placeholder={t("confirmPasswordPlaceholder")} required className={inputClassName} />
      </div>

      {status === "error" && (
        <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-600 sm:col-span-2">
          {errorMessage}
        </p>
      )}

      <div className="sm:col-span-2 pt-3">
        <button
          type="submit"
          disabled={status === "loading"}
          className="flex w-full transform items-center justify-center gap-3 rounded-xl bg-emerald-600 px-6 py-3.5 sm:py-4 text-base sm:text-lg font-bold tracking-wide text-white shadow-lg shadow-emerald-600/30 transition-all duration-200 hover:bg-emerald-700 hover:shadow-xl focus:outline-none focus:ring-4 focus:ring-emerald-300 disabled:opacity-60 active:scale-[0.99]"
        >
          <span>{status === "loading" ? t("submitting") : t("submit")}</span>
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 rtl:-scale-x-100" viewBox="0 0 20 20" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z"
              clipRule="evenodd"
            />
          </svg>
        </button>
      </div>

      <p className="sm:col-span-2 mt-2 text-center text-sm text-slate-600">
        {t("hasAccount")}{" "}
        <a href="/fr/signin" className="font-semibold text-emerald-600 hover:text-emerald-700 hover:underline">
          {t("signInLink")}
        </a>
      </p>
    </form>
  );
}

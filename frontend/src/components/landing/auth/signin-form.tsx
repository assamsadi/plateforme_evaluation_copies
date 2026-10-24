"use client";

import { type FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import Image from "next/image";
import logo from "../../../../public/images/logo-c2pct.png";

import { Link, useRouter } from "@/i18n/navigation";
import { AuthApiError, login, loginWithGoogle } from "@/lib/auth-api";
import { useAuth } from "@/lib/auth-context";
import { dashboardHomeFor } from "@/navigation/sidebar/sidebar-items";

import { GoogleSignInButton } from "./google-signin-button";

const inputClassName =
  "block w-full rounded-xl border border-slate-300 bg-white px-4 py-3.5 sm:py-4 text-base sm:text-lg text-slate-800 placeholder:text-transparent hover:placeholder:text-slate-400 focus:placeholder:text-slate-400 shadow-sm transition-all focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/20 focus:outline-none";

export default function SignInForm() {
  const t = useTranslations("Auth.signIn");
  const router = useRouter();
  const { setSession } = useAuth();
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  // Traitement commun connexion classique / Google — même forme de réponse
  // (LoginResult) des deux côtés, cf. leurs docstrings respectives.
  async function handleLoginResult(resultPromise: ReturnType<typeof login>) {
    try {
      const result = await resultPromise;

      if (result.mfaRequired) {
        setStatus("error");
        setErrorMessage(t("mfaNotSupported"));
        return;
      }

      setSession(result.accessToken, result.refreshToken, result.user);
      setStatus("success");
      router.push(dashboardHomeFor(result.user.role));
    } catch (error) {
      setStatus("error");
      setErrorMessage(error instanceof AuthApiError ? error.message || t("genericError") : t("networkError"));
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setErrorMessage("");

    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email"));
    const password = String(formData.get("password"));

    await handleLoginResult(login(email, password));
  }

  async function handleGoogleCredential(credential: string) {
    setStatus("loading");
    setErrorMessage("");
    await handleLoginResult(loginWithGoogle(credential));
  }

  return (
    <div className="w-full">
      <div className="mx-auto flex justify-center">
        <Link href="/" className="inline-flex shrink-0 items-center transition-transform hover:scale-105" aria-label="Accueil">
          <Image
            src={logo}
            alt="Logo C2PCT Assess"
            width={1324}
            height={318}
            priority
            className="h-12 sm:h-14 md:h-16 w-auto object-contain"
          />
        </Link>
      </div>

      <p className="mt-5 text-center font-nacelle text-2xl sm:text-3xl font-bold text-slate-800">{t("welcomeBack")}</p>

      <div className="mt-8">
        <GoogleSignInButton onCredential={handleGoogleCredential}>
          <div className="flex w-full items-center justify-center gap-3.5 rounded-2xl border-2 border-slate-200 bg-white py-4 px-6 text-slate-800 shadow-md shadow-slate-200/50 transition-all duration-200 hover:border-emerald-500/50 hover:bg-slate-50/80 hover:shadow-lg hover:shadow-emerald-500/10 active:scale-[0.99] cursor-pointer">
            <svg className="h-7 w-7 shrink-0" viewBox="0 0 40 40">
              <path
                d="M36.3425 16.7358H35V16.6667H20V23.3333H29.4192C28.045 27.2142 24.3525 30 20 30C14.4775 30 10 25.5225 10 20C10 14.4775 14.4775 9.99999 20 9.99999C22.5492 9.99999 24.8683 10.9617 26.6342 12.5325L31.3483 7.81833C28.3717 5.04416 24.39 3.33333 20 3.33333C10.7958 3.33333 3.33335 10.7958 3.33335 20C3.33335 29.2042 10.7958 36.6667 20 36.6667C29.2042 36.6667 36.6667 29.2042 36.6667 20C36.6667 18.8825 36.5517 17.7917 36.3425 16.7358Z"
                fill="#FFC107"
              />
              <path
                d="M5.25497 12.2425L10.7308 16.2583C12.2125 12.59 15.8008 9.99999 20 9.99999C22.5491 9.99999 24.8683 10.9617 26.6341 12.5325L31.3483 7.81833C28.3716 5.04416 24.39 3.33333 20 3.33333C13.5983 3.33333 8.04663 6.94749 5.25497 12.2425Z"
                fill="#FF3D00"
              />
              <path
                d="M20 36.6667C24.305 36.6667 28.2167 35.0192 31.1742 32.34L26.0159 27.975C24.3425 29.2425 22.2625 30 20 30C15.665 30 11.9842 27.2359 10.5975 23.3784L5.16254 27.5659C7.92087 32.9634 13.5225 36.6667 20 36.6667Z"
                fill="#4CAF50"
              />
              <path
                d="M36.3425 16.7358H35V16.6667H20V23.3333H29.4192C28.7592 25.1975 27.56 26.805 26.0133 27.9758C26.0142 27.975 26.015 27.975 26.0158 27.9742L31.1742 32.3392C30.8092 32.6708 36.6667 28.3333 36.6667 20C36.6667 18.8825 36.5517 17.7917 36.3425 16.7358Z"
                fill="#1976D2"
              />
            </svg>
            <span className="text-base sm:text-lg font-bold text-slate-800">{t("googleSignIn")}</span>
          </div>
        </GoogleSignInButton>
      </div>

      <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
        <div>
          <label htmlFor="email" className="mb-2 block text-base sm:text-lg font-semibold text-slate-700">
            {t("email")}
          </label>
          <input id="email" name="email" type="email" placeholder={t("emailPlaceholder")} required className={inputClassName} />
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label htmlFor="password" className="block text-base sm:text-lg font-semibold text-slate-700">
              {t("password")}
            </label>
            <Link href="/reset-password" className="text-sm font-semibold text-emerald-600 hover:text-emerald-700 hover:underline">
              {t("forgotPassword")}
            </Link>
          </div>
          <input id="password" name="password" type="password" placeholder={t("passwordPlaceholder")} required className={inputClassName} />
        </div>

        {status === "error" && (
          <p className="rounded-xl border border-red-200 bg-red-50 p-3.5 text-sm font-semibold text-red-600">
            {errorMessage}
          </p>
        )}

        <div className="pt-3">
          <button
            type="submit"
            disabled={status === "loading"}
            className="w-full transform rounded-xl bg-emerald-600 px-6 py-4 sm:py-4.5 text-lg sm:text-xl font-bold tracking-wide text-white shadow-lg shadow-emerald-600/30 transition-all duration-200 hover:bg-emerald-700 hover:shadow-xl focus:outline-none focus:ring-4 focus:ring-emerald-300 disabled:opacity-60 active:scale-[0.99]"
          >
            {status === "loading" ? t("submitting") : t("submit")}
          </button>
        </div>
      </form>

      <div className="mt-6 flex items-center justify-between">
        <span className="w-1/4 border-b border-slate-200" />
        <Link href="/signup" className="text-sm font-semibold uppercase tracking-wider text-slate-500 hover:text-emerald-700 hover:underline">
          {t("orSignUpDivider")}
        </Link>
        <span className="w-1/4 border-b border-slate-200" />
      </div>
    </div>
  );
}

import { getTranslations } from "next-intl/server";

export async function generateMetadata() {
  const t = await getTranslations("Auth.resetPassword");
  return { title: t("title") };
}

export default async function ResetPassword() {
  const t = await getTranslations("Auth.resetPassword");

  return (
    <section className="flex grow items-center justify-center px-4 py-20">
      <div className="w-full max-w-[400px] rounded-2xl border border-gray-100 bg-white/90 p-8 shadow-xl shadow-emerald-900/5 backdrop-blur-sm">
        <h1 className="mb-8 text-center font-nacelle text-2xl font-semibold text-gray-900">
          {t("title")}
        </h1>

        <form className="space-y-5">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-600" htmlFor="email" title={t("emailPlaceholder")}>
              {t("email")}
            </label>
            <input id="email" type="email" className="form-input w-full" placeholder={t("emailPlaceholder")} />
          </div>
          <div className="flex justify-center">
            <button
              className="btn rounded-lg text-sm font-semibold text-white shadow-sm transition-transform hover:scale-[1.01]"
              style={{ background: "linear-gradient(135deg, #059669 0%, #10b981 50%, #34d399 100%)" }}
            >
              {t("submit")}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}

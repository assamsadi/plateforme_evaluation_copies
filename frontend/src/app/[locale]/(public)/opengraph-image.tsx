import { ImageResponse } from "next/og";
import { getTranslations } from "next-intl/server";

export const alt = "Plateforme d'évaluation de copies";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OpengraphImage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Metadata" });

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 50%, #ffffff 100%)",
          padding: "80px",
        }}
      >
        <div
          style={{
            display: "flex",
            fontSize: 64,
            fontWeight: 700,
            textAlign: "center",
            lineHeight: 1.15,
            backgroundImage: "linear-gradient(135deg, #059669 0%, #10b981 50%, #34d399 100%)",
            backgroundClip: "text",
            color: "transparent",
          }}
        >
          {t("title")}
        </div>
        <div
          style={{
            display: "flex",
            marginTop: 32,
            fontSize: 30,
            color: "#4b5563",
            textAlign: "center",
            maxWidth: 900,
            lineHeight: 1.4,
          }}
        >
          {t("description")}
        </div>
      </div>
    ),
    { ...size },
  );
}

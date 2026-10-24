import packageJson from "../../package.json";

const currentYear = new Date().getFullYear();

export const APP_CONFIG = {
  name: "Plateforme d'évaluation de copies",
  version: packageJson.version,
  copyright: `© ${currentYear} — Plateforme d'évaluation de copies.`,
  meta: {
    title: "Espace administration — Plateforme d'évaluation de copies",
    description:
      "Espace de gestion pour les administrateurs, professeurs et étudiants de la plateforme d'évaluation de copies assistée par IA.",
  },
};

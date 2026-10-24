/**
 * Dictionnaire statique et sûr des 15 sous-questions de la méthodologie C2PCT.
 * Résout le problème des clés dynamiques avec des points (ex. "1.1") dans next-intl.
 */

export const C2PCT_SUBQUESTIONS_I18N: Record<
  string,
  { en: string; fr: string; es: string }
> = {
  "1.1": {
    en: "List and categorize data (Problem/Question)",
    fr: "Lister et catégoriser les données (Problème/Question)",
    es: "Listar y categorizar datos (Problema/Pregunta)",
  },
  "1.2": {
    en: "Identify what is requested and conditions to respect",
    fr: "Identifier ce qui est demandé et les conditions à respecter",
    es: "Identificar lo solicitado y condiciones a respetar",
  },
  "1.3": {
    en: "Determine necessary data to answer",
    fr: "Déterminer les données nécessaires pour répondre",
    es: "Determinar datos necesarios para responder",
  },
  "1.4": {
    en: "Problem representation (diagram/drawing)",
    fr: "Représentation du problème (schéma/dessin)",
    es: "Representación del problema (esquema/dibujo)",
  },
  "1.5": {
    en: "Identify missing data to calculate",
    fr: "Identifier les données manquantes, à calculer",
    es: "Identificar datos faltantes, a calcular",
  },
  "2.1": {
    en: "Identify necessary complement (formula/technique/rule)",
    fr: "Identifier le complément nécessaire (formule/technique/règle)",
    es: "Identificar complemento necesario (fórmula/técnica/regla)",
  },
  "2.2": {
    en: "Divide problem into sub-problems",
    fr: "Diviser le problème en mini-problèmes",
    es: "Dividir problema en subproblemas",
  },
  "3.1": {
    en: "Describe resolution steps in words",
    fr: "Décrire les étapes de résolution en mots",
    es: "Describir pasos de resolución en palabras",
  },
  "3.2": {
    en: "Visual representation of steps (diagram)",
    fr: "Représentation visuelle des étapes (schéma)",
    es: "Representación visual de los pasos (esquema)",
  },
  "4": {
    en: "Identify another problem/context reusing this solution",
    fr: "Identifier un autre problème/contexte réutilisant cette solution",
    es: "Identificar otro problema/contexto reutilizando esta solución",
  },
  "5": {
    en: "Write final response presented to teacher",
    fr: "Rédiger la réponse finale présentée au professeur",
    es: "Redactar la respuesta final presentada al profesor",
  },
  "6.1": {
    en: "Does result make sense, answer the question asked",
    fr: "Le résultat a-t-il un sens, répond-il à la question posée",
    es: "¿Tiene sentido el resultado? ¿Responde a la pregunta?",
  },
  "6.2": {
    en: "Is this the best possible solution, does alternative exist",
    fr: "Est-ce la meilleure solution possible, une alternative existe-t-elle",
    es: "¿Es la mejor solución posible? ¿Existe alternativa?",
  },
  "7.1": {
    en: "Difficulties encountered in understanding problem",
    fr: "Difficultés rencontrées dans la compréhension du problème",
    es: "Dificultades encontradas al comprender el problema",
  },
  "7.2": {
    en: "Usefulness of structure followed to solve problem",
    fr: "Utilité de la structure suivie pour résoudre le problème",
    es: "Utilidad de la estructura seguida para resolver el problema",
  },
};

/**
 * Formate un item de force ou de faiblesse en extrayant son id (ex: "1.1" depuis "1.1 (texte...)")
 * et en retournant la version traduite sans jamais afficher de clés brutes.
 */
export function formatC2PCTItem(raw: string, locale: string = "en"): string {
  if (!raw) return "";

  // Extraction de l'identifiant initial (ex: "1.1", "3.2", "4", etc.)
  const match = raw.match(/^(\d+(?:\.\d+)?)\s*(?:[—\-\(]|\s)(.*)$/);
  const sqId = match ? match[1] : raw.trim();

  const translations = C2PCT_SUBQUESTIONS_I18N[sqId];
  if (translations) {
    const lang = (locale.startsWith("fr") ? "fr" : locale.startsWith("es") ? "es" : "en") as "en" | "fr" | "es";
    return `${sqId} — ${translations[lang]}`;
  }

  // Si pas de correspondance dans les 15 items, nettoyer les parenthèses sans bug
  if (match) {
    const cleanLabel = match[2].replace(/\)+$/, "").trim();
    return `${match[1]} — ${cleanLabel}`;
  }

  return raw;
}

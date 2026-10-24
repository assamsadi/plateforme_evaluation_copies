"use client";

import { useMemo } from "react";

import katex from "katex";

import { cn } from "@/lib/utils";

/**
 * Un FRAGMENT (jamais une ligne entière, cf. bug réel corrigé ci-dessous)
 * n'est envoyé à KaTeX que s'il contient un signal syntaxique mécanique de
 * LaTeX (`\frac`, `_1`, `^2`...) — jamais une heuristique sémantique sur le
 * CONTENU (on ne devine jamais "ceci est une sous-question C2PCT" ou "ceci
 * est une réponse") : uniquement vérifiable par KaTeX lui-même (rendu
 * essayé, texte brut en repli silencieux si le parsing échoue).
 */
const LATEX_MACRO_PATTERN = /[\\_^]/;

// Bug réel corrigé (2026-09-04, variantes de solution générées par IA) :
// une ligne de prose mêlant du texte naturel ET une formule inline (ex.
// "on confirme les efforts axiaux N_1 = -6P et N_5 = 3\sqrt{5}P.") faisait
// passer TOUTE la ligne — accents français compris — dans KaTeX, qui la
// rendait caractère par caractère de façon illisible (KaTeX n'a aucune
// notion de prose, seulement de formules). Un token "mathématique" est
// désormais repéré comme un fragment SANS ESPACE contenant au moins un
// `\`, `_` ou `^` — un mot de prose normal n'en contient jamais, une
// formule inline si (commande, indice, exposant) — et seul CE fragment est
// rendu par KaTeX, jamais son voisinage en français.
const MATH_TOKEN_PATTERN = /\S*[\\_^]\S*/g;

function renderKatexHtml(source: string): string | null {
  try {
    return katex.renderToString(source, {
      throwOnError: true,
      displayMode: false,
      strict: "ignore",
    });
  } catch {
    return null;
  }
}

/** Découpe une ligne en segments texte/maths alternés, jamais l'un OU l'autre pour la ligne entière. */
function splitMathSegments(line: string): { type: "text" | "math"; value: string }[] {
  const segments: { type: "text" | "math"; value: string }[] = [];
  let lastIndex = 0;
  for (const match of line.matchAll(MATH_TOKEN_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      segments.push({ type: "text", value: line.slice(lastIndex, index) });
    }
    segments.push({ type: "math", value: match[0] });
    lastIndex = index + match[0].length;
  }
  if (lastIndex < line.length) {
    segments.push({ type: "text", value: line.slice(lastIndex) });
  }
  return segments;
}

function renderLine(line: string, key: number) {
  if (!LATEX_MACRO_PATTERN.test(line)) {
    return (
      <p key={key} className="leading-relaxed break-words">
        {line}
      </p>
    );
  }

  const segments = splitMathSegments(line);
  return (
    <p key={key} className="leading-relaxed break-words">
      {segments.map((segment, segIndex) => {
        if (segment.type === "text") {
          return segment.value ? <span key={segIndex}>{segment.value}</span> : null;
        }
        const html = renderKatexHtml(segment.value);
        if (!html) {
          return <span key={segIndex}>{segment.value}</span>;
        }
        return (
          // biome-ignore lint/security/noDangerouslySetInnerHtml: sortie KaTeX générée localement (jamais injectée depuis une source externe non fiable)
          <span key={segIndex} className="mx-0.5 inline-block align-middle" dangerouslySetInnerHTML={{ __html: html }} />
        );
      })}
    </p>
  );
}

export function LatexText({ text, className }: { text: string; className?: string }) {
  const lines = useMemo(() => text.split("\n"), [text]);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) return null;
        return renderLine(trimmed, index);
      })}
    </div>
  );
}

/**
 * Variante pour un champ qui est TOUJOURS une formule isolée (ex.
 * `ReasoningStep.formula`), jamais un bloc de prose à découper ligne par
 * ligne — rendu KaTeX si possible, texte brut en repli sinon (même
 * discipline try/catch que LatexText).
 */
export function LatexInline({ text, className }: { text: string; className?: string }) {
  const trimmed = text.trim();
  const html = LATEX_MACRO_PATTERN.test(trimmed) ? renderKatexHtml(trimmed) : null;

  if (html) {
    return (
      // biome-ignore lint/security/noDangerouslySetInnerHtml: sortie KaTeX générée localement
      <span className={cn("inline-block overflow-x-auto align-middle", className)} dangerouslySetInnerHTML={{ __html: html }} />
    );
  }
  return <span className={cn("font-mono break-words", className)}>{trimmed}</span>;
}

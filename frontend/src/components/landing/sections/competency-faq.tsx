"use client";

import { useState } from "react";

export interface CompetencyData {
  key: string;
  title: string;
  subquestions: string[];
}

// Accordéon des 7 compétences C2PCT — remplace l'ancienne roue interactive
// (cf. mémoire de session). Même source de données (CompetencyData) que
// l'ancien composant, seule la présentation change : chaque compétence est
// une question repliable, ses sous-questions officielles en forment la
// réponse (jamais un texte réécrit — le même contenu que competency-wheel.tsx
// transmettait déjà à la roue).
export function CompetencyFaq({ competencies }: { competencies: CompetencyData[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(0);

  return (
    <div className="mx-auto mt-14 flex w-full max-w-4xl lg:max-w-5xl flex-col gap-5">
      {competencies.map((competency, index) => {
        const isOpen = openIndex === index;
        return (
          <div
            key={competency.key}
            className="flex w-full flex-col overflow-hidden rounded-2xl border border-emerald-100/90 bg-white/85 shadow-sm backdrop-blur-md transition-all duration-200 hover:border-emerald-300 hover:shadow-md"
          >
            <button
              type="button"
              onClick={() => setOpenIndex(isOpen ? null : index)}
              className="flex w-full items-center justify-between gap-4 px-6 py-5 sm:px-8 sm:py-6 text-left transition-colors bg-gradient-to-r from-emerald-50/50 to-white/70 hover:from-emerald-50/80 hover:to-white"
              aria-expanded={isOpen}
            >
              <span className="flex items-center gap-4 sm:gap-5">
                <span className="flex size-10 sm:size-11 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-base sm:text-lg font-bold text-emerald-700 shadow-sm">
                  {index + 1}
                </span>
                <span className="font-nacelle text-xl font-bold text-slate-900 sm:text-2xl">
                  {competency.title}
                </span>
              </span>
              <svg
                width="24"
                height="24"
                viewBox="0 0 18 18"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className={`shrink-0 transition-transform duration-300 ease-in-out ${isOpen ? "rotate-180" : ""}`}
              >
                <path
                  d="m4.5 7.2 3.793 3.793a1 1 0 0 0 1.414 0L13.5 7.2"
                  stroke="#047857"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            <ul
              className={`flex flex-col gap-3 overflow-hidden px-6 sm:px-12 text-base sm:text-lg text-slate-700 transition-all duration-300 ease-in-out ${
                isOpen ? "max-h-[500px] translate-y-0 pt-4 pb-6 opacity-100" : "max-h-0 -translate-y-2 opacity-0"
              }`}
            >
              {competency.subquestions.map((subquestion) => (
                <li key={subquestion} className="flex items-start gap-3.5 leading-relaxed">
                  <span className="mt-2.5 size-2 shrink-0 rounded-full bg-emerald-500" />
                  <span>{subquestion}</span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

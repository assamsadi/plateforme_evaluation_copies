// Police Caveat chargée dans registry.ts (fontVars → --font-handwriting).
// Ce fichier conservé pour compatibilité mais ne doit plus exporter de
// classe next/font — utiliser [font-family:var(--font-handwriting)] en CSS.

/**
 * @deprecated Use `[font-family:var(--font-handwriting)]` Tailwind class directly.
 * The Caveat font is loaded globally via registry.ts → fontVars.
 */
export const handwritingFont = { className: "[font-family:var(--font-handwriting)]" };

"use client";

const ICONS: Record<string, React.ReactNode> = {
  analysis: (
    <svg className="h-11 w-11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
      <rect x="9" y="3" width="6" height="4" rx="1" />
      <path d="M9 12h6M9 16h4" />
    </svg>
  ),
  validation: (
    <svg className="h-11 w-11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  ),
  traceability: (
    <svg className="h-11 w-11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  ),
};

interface Item {
  key: string;
  title: string;
  description: string;
}

export function GlowCards({ items }: { items: Item[] }) {
  return (
    <div className="mt-16 grid gap-8 sm:grid-cols-3 lg:gap-12">
      {items.map((item) => (
        <div
          key={item.key}
          className="group relative flex min-h-[440px] sm:min-h-[480px] flex-col justify-start select-none overflow-hidden rounded-[2rem] border-2 border-emerald-500 bg-white p-10 sm:p-12 lg:p-14 shadow-lg transition-all duration-300 hover:border-emerald-600 hover:shadow-2xl hover:-translate-y-1"
        >
          <div className="relative z-10">
            {/* Icône grand format avec style émeraude élégant */}
            <div className="mb-10 inline-flex h-22 w-22 items-center justify-center rounded-3xl bg-gradient-to-br from-emerald-50 to-teal-50 text-emerald-600 ring-1 ring-emerald-200 sm:h-24 sm:w-24 shadow-sm transition-transform duration-300 group-hover:scale-105">
              {ICONS[item.key]}
            </div>

            {/* Titre large */}
            <h3 className="font-nacelle text-2xl font-bold text-slate-900 sm:text-3xl lg:text-4xl leading-snug">
              {item.title}
            </h3>

            {/* Description aérée */}
            <p className="mt-6 text-lg sm:text-xl lg:text-2xl leading-relaxed text-slate-600">
              {item.description}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

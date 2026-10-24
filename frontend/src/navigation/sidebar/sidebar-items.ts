import {
  Bot,
  BookOpen,
  FileEdit,
  GraduationCap,
  LayoutDashboard,
  type LucideIcon,
  MessageCircleQuestion,
  ScrollText,
  Scale,
  Settings,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  UploadCloud,
  Users,
} from "lucide-react";

export type NavBadge = "new" | "soon";

// number : compteur dynamique (ex. clarifications bloquantes en attente) —
// injecté à l'exécution par AppSidebar, jamais une valeur statique posée ici
// (contrairement à "new"/"soon", fixes par item). Rendu distinctement par
// NavItemBadge (rouge, jamais confondu avec "new"/"soon").
export interface NavSubItem {
  id: string;
  title: string;
  url: string;
  icon?: LucideIcon;
  badge?: NavBadge | number;
  disabled?: boolean;
  newTab?: boolean;
}

interface NavItemBase {
  id: string;
  title: string;
  icon?: LucideIcon;
  badge?: NavBadge | number;
  disabled?: boolean;
  newTab?: boolean;
}

export interface NavMainLinkItem extends NavItemBase {
  url: string;
  subItems?: never;
}

export interface NavMainParentItem extends NavItemBase {
  subItems: NavSubItem[];
}

export type NavMainItem = NavMainLinkItem | NavMainParentItem;

export interface NavGroup {
  id: number;
  label?: string;
  items: NavMainItem[];
}

// Template de démo (CRM, finance, e-commerce, logistics, kanban, mail,
// chat, calendar, tasks, academy, roles, profile, legacy...) entièrement
// supprimé — aucune de ces pages ne correspondait à un vrai endpoint
// backend. Reconstruction au fur et à mesure des besoins réels, avec le
// même design system (cf. Users, déjà reconstruit).
export const adminSidebarItems: NavGroup[] = [
  {
    id: 1,
    items: [
      {
        id: "default",
        title: "Dashboard",
        url: "/dashboard/default",
        icon: LayoutDashboard,
      },
      {
        id: "users",
        title: "Users",
        url: "/dashboard/users",
        icon: Users,
      },
      {
        id: "programs",
        title: "Programs",
        url: "/dashboard/programs",
        icon: GraduationCap,
      },
      {
        id: "audit-logs",
        title: "Audit Logs",
        url: "/dashboard/audit-logs",
        icon: ScrollText,
      },
      {
        id: "integrity-alerts",
        title: "Integrity Alerts",
        url: "/dashboard/integrity-alerts",
        icon: ShieldAlert,
      },
      {
        id: "system-config",
        title: "System Config",
        icon: Settings,
        subItems: [
          { id: "system-config-models", title: "AI Models", url: "/dashboard/system-config/models" },
          { id: "system-config-credentials", title: "APIs", url: "/dashboard/system-config/credentials" },
          { id: "system-config-settings", title: "Settings", url: "/dashboard/system-config/settings" },
        ],
      },
      {
        id: "agent-decisions",
        title: "Agent Decisions",
        url: "/dashboard/agent-decisions",
        icon: Bot,
      },
      {
        id: "privacy-requests",
        title: "Privacy Requests",
        url: "/dashboard/privacy-requests",
        icon: ShieldCheck,
      },
    ],
  },
];

export const professorSidebarItems: NavGroup[] = [
  {
    id: 1,
    label: "Teaching",
    items: [
      {
        id: "my-courses",
        title: "My Courses",
        url: "/dashboard/my-courses",
        icon: BookOpen,
      },
      {
        id: "exercises",
        title: "Exercises",
        url: "/dashboard/exercises",
        icon: FileEdit,
      },
      {
        id: "clarifications",
        title: "Clarifications",
        url: "/dashboard/clarifications",
        icon: MessageCircleQuestion,
      },
      {
        id: "arbitration",
        title: "Arbitration",
        icon: Scale,
        subItems: [
          { id: "arbitration-corrections", title: "Contestations", url: "/dashboard/arbitration/corrections" },
          { id: "arbitration-incidents", title: "Incidents", url: "/dashboard/arbitration/incidents" },
          { id: "arbitration-appeals", title: "Appeals", url: "/dashboard/arbitration/appeals" },
        ],
      },
    ],
  },
];

export const studentSidebarItems: NavGroup[] = [
  {
    id: 1,
    label: "Studying",
    items: [
      {
        id: "my-exams",
        title: "My Exams",
        url: "/dashboard/my-exams",
        icon: UploadCloud,
      },
      {
        id: "my-progress",
        title: "My Progress",
        url: "/dashboard/my-progress",
        icon: TrendingUp,
      },
    ],
  },
];

export function getSidebarItems(role: string | undefined): NavGroup[] {
  if (role === "admin") return adminSidebarItems;
  if (role === "professor") return professorSidebarItems;
  if (role === "student") return studentSidebarItems;
  return [];
}

/**
 * Bug corrigé (rapport utilisateur) : un professeur nouvellement créé
 * atterrissait sur /dashboard/default (admin uniquement, cf. AuthGuard de
 * cette page) après connexion, et le lien "Go to Homepage" de la page
 * /unauthorized y renvoyait aussi — boucle de blocage totale pour tout
 * professeur. dashboardDestinationFor (signin-form.tsx) renvoyait
 * inconditionnellement "/dashboard/default" quelle que soit `role`, un
 * reliquat du tout début du chantier où seul l'espace admin existait
 * réellement. Espace student ajouté depuis (cf. studentSidebarItems) —
 * même correctif appliqué ici pour ne pas répéter le même piège.
 */
export function dashboardHomeFor(role: string | undefined): string {
  if (role === "professor") return "/dashboard/my-courses";
  if (role === "student") return "/dashboard/my-exams";
  return "/dashboard/default";
}

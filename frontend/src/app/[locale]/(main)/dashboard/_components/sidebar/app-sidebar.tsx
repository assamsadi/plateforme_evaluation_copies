"use client";

import { useEffect, useState } from "react";

import { useShallow } from "zustand/react/shallow";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { APP_CONFIG } from "@/config/app-config";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { getStoredSession } from "@/lib/auth-api";
import { listPendingClarifications } from "@/lib/professor-api";
import { listAssignedExercises } from "@/lib/student-api";
import {
  getSidebarItems,
  type NavGroup,
  type NavMainItem,
  type NavMainLinkItem,
  type NavSubItem,
} from "@/navigation/sidebar/sidebar-items";
import { usePreferencesStore } from "@/stores/preferences/preferences-provider";

import { NavMain } from "./nav-main";
import { NavUser } from "./nav-user";

// Injecte un compteur dynamique sur l'item de menu ciblé (id) sans muter
// getSidebarItems (constante partagée) — nouvelle structure à chaque appel,
// jamais un effet de bord sur le tableau statique d'origine.
function withBadgeCount(groups: NavGroup[], itemId: string, count: number): NavGroup[] {
  return groups.map((group) => ({
    ...group,
    items: group.items.map((item) => (item.id === itemId ? { ...item, badge: count > 0 ? count : undefined } : item)),
  }));
}

// Convertit l'item ciblé (lien simple) en parent avec un sous-item par
// module — même principe que withBadgeCount (nouvelle structure à chaque
// appel, jamais de mutation de getSidebarItems). Ignoré si moins de 2
// modules (un seul module : le lien direct suffit, un sous-menu à une
// entrée n'apporte rien).
function withModuleSubItems(groups: NavGroup[], itemId: string, subItems: NavSubItem[]): NavGroup[] {
  if (subItems.length < 2) return groups;
  return groups.map((group) => ({
    ...group,
    items: group.items.map((item): NavMainItem => {
      if (item.id !== itemId) return item;
      const { url: _url, ...rest } = item as NavMainLinkItem;
      void _url;
      return { ...rest, subItems };
    }),
  }));
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  const { sidebarVariant, sidebarCollapsible, isSynced } = usePreferencesStore(
    useShallow((s) => ({
      sidebarVariant: s.values.sidebar_variant,
      sidebarCollapsible: s.values.sidebar_collapsible,
      isSynced: s.isSynced,
    })),
  );
  const { user } = useAuth();
  const [blockingClarificationCount, setBlockingClarificationCount] = useState(0);
  const [progressModuleSubItems, setProgressModuleSubItems] = useState<NavSubItem[]>([]);

  // "My Progress" en sous-sections par module — un étudiant assigné à
  // plusieurs modules doit pouvoir naviguer directement vers chacun depuis
  // la sidebar, plutôt que passer systématiquement par le sélecteur en haut
  // de la page. Dérivé de listAssignedExercises (aucun endpoint dédié
  // "mes modules" côté étudiant, même source que la page elle-même).
  useEffect(() => {
    if (user?.role !== "student") return;

    let cancelled = false;

    async function fetchModules() {
      const session = getStoredSession();
      if (!session) return;
      try {
        const page = await listAssignedExercises(session.accessToken, { limit: 200 });
        if (cancelled) return;
        const seen = new Map<string, string>();
        for (const exercise of page.items) seen.set(exercise.module_id, exercise.module_name);
        setProgressModuleSubItems(
          Array.from(seen, ([id, name]) => ({
            id: `my-progress-${id}`,
            title: name,
            url: `/dashboard/my-progress?module_id=${id}`,
          })),
        );
      } catch {
        // Best-effort : un échec ici laisse simplement le lien direct "My Progress".
      }
    }

    fetchModules();
    return () => {
      cancelled = true;
    };
  }, [user?.role]);

  // Indice visible en permanence (cf. rapport utilisateur : une clarification
  // BLOCKING peut rester ignorée si le professeur ne pense pas à ouvrir cet
  // onglet précis) — scope volontairement restreint à BLOCKING seulement,
  // jamais WARNING/INFORMATIONAL (pas la même urgence, éviter le bruit).
  // Poll léger (60s) plutôt qu'un flux temps réel : aucune infrastructure de
  // notification push n'existe encore côté backend pour ce cas.
  useEffect(() => {
    if (user?.role !== "professor") return;

    let cancelled = false;

    async function fetchCount() {
      const session = getStoredSession();
      if (!session) return;
      try {
        const pending = await listPendingClarifications(session.accessToken);
        if (!cancelled) {
          setBlockingClarificationCount(pending.filter((r) => r.severity === "blocking").length);
        }
      } catch {
        // Best-effort : un échec de ce poll ne doit jamais casser la sidebar.
      }
    }

    fetchCount();
    const interval = setInterval(fetchCount, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [user?.role]);

  const sidebarItems = withModuleSubItems(
    withBadgeCount(getSidebarItems(user?.role), "clarifications", blockingClarificationCount),
    "my-progress",
    progressModuleSubItems,
  );

  const variant = isSynced ? sidebarVariant : props.variant;
  const collapsible = isSynced ? sidebarCollapsible : props.collapsible;

  return (
    <Sidebar {...props} variant={variant} collapsible={collapsible}>
      <SidebarHeader className="border-b border-sidebar-border pb-4">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild className="h-auto py-2">
              <Link prefetch={false} href="/dashboard/default">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/logo-c2pct-assess.png"
                  alt={APP_CONFIG.name}
                  className="h-16 w-auto group-data-[collapsible=icon]:hidden"
                />
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={sidebarItems} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
    </Sidebar>
  );
}

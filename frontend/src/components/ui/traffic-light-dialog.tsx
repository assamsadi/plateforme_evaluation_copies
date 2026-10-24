"use client";

import type { ReactNode } from "react";

import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * Thème "carte feu tricolore" établi sur toute la plateforme admin cette
 * session (bandeau 3 pastilles, fond clair, zone de contenu scrollable
 * dédiée) — extrait ici en composant partagé après avoir été copié-collé
 * dans ~6 dialogs. footer optionnel : mx-0/mb-0 posés une fois pour toutes
 * ici annulent les -mx-4/-mb-4 par défaut de DialogFooter (pensés pour un
 * DialogContent p-4 standard) — root cause du bouton "Fermer" déjà rogné
 * plusieurs fois avant cette extraction.
 */
export function TrafficLightDialog({
  open,
  onOpenChange,
  children,
  footer,
  contentClassName,
  bodyClassName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  footer?: ReactNode;
  contentClassName?: string;
  bodyClassName?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex max-h-[85vh] flex-col overflow-hidden rounded-2xl border-0 bg-[#F8FBFE] p-0 shadow-2xl ring-1 ring-black/10 dark:bg-zinc-900 dark:ring-white/10",
          contentClassName,
        )}
      >
        <div className="flex shrink-0 items-center gap-1.5 border-b border-black/5 px-4 py-3 dark:border-white/10">
          <span className="size-3 rounded-full bg-[#ff605c]" />
          <span className="size-3 rounded-full bg-[#ffbd44]" />
          <span className="size-3 rounded-full bg-[#00ca4e]" />
        </div>
        <div className={cn("min-h-0 flex-1 overflow-y-auto p-6", bodyClassName)}>{children}</div>
        {footer ? (
          <DialogFooter className="mx-0 mb-0 shrink-0 gap-2 border-t border-black/5 bg-muted/50 p-4 sm:justify-end dark:border-white/10">
            {footer}
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

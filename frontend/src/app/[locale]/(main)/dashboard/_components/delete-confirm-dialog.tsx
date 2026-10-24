"use client";

import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export function DeleteConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  cancelLabel,
  confirmLabel,
  isPending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  cancelLabel: string;
  confirmLabel: string;
  isPending: boolean;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="flex max-h-[85vh] flex-col overflow-hidden rounded-2xl border-0 bg-[#F8FBFE] p-0 shadow-2xl ring-1 ring-black/10 sm:max-w-md dark:bg-zinc-900 dark:ring-white/10">
        <div className="flex shrink-0 items-center gap-1.5 border-b border-black/5 px-4 py-3 dark:border-white/10">
          <span className="size-3 rounded-full bg-[#ff605c]" />
          <span className="size-3 rounded-full bg-[#ffbd44]" />
          <span className="size-3 rounded-full bg-[#00ca4e]" />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <AlertDialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-destructive/20 bg-destructive/10 text-destructive">
                <AlertTriangle className="size-5" />
              </div>
              <AlertDialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{title}</AlertDialogTitle>
            </div>
            <AlertDialogDescription className="text-sm font-medium leading-relaxed text-slate-600 dark:text-zinc-400">
              {description}
            </AlertDialogDescription>
          </AlertDialogHeader>
        </div>

        <AlertDialogFooter className="mx-0 mb-0 shrink-0 gap-2 border-t bg-muted/50 p-4 sm:justify-end">
          <AlertDialogCancel
            disabled={isPending}
            className="h-9 rounded-xl border-slate-200 px-4 text-sm font-semibold text-slate-700 hover:border-slate-300 hover:bg-slate-50 dark:border-zinc-700 dark:text-zinc-300"
          >
            {cancelLabel}
          </AlertDialogCancel>
          <AlertDialogAction
            variant="skew-destructive"
            disabled={isPending}
            onClick={(event) => {
              event.preventDefault();
              onConfirm();
            }}
            className="h-9 px-4 text-sm font-semibold tracking-wide"
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

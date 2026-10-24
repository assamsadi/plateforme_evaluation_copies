"use client";

import type { MouseEvent } from "react";

import type { ReactTable, RowData } from "@tanstack/react-table";
import { useTranslations } from "next-intl";

import { Card } from "@/components/ui/card";
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

function preventPaginationNavigation(event: MouseEvent<HTMLAnchorElement>) {
  event.preventDefault();
}

function getPageNumbers(currentPage: number, pageCount: number) {
  if (pageCount <= 3) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  if (currentPage <= 2) return [1, 2, 3];
  if (currentPage >= pageCount - 1) return [pageCount - 2, pageCount - 1, pageCount];

  return [currentPage - 1, currentPage, currentPage + 1];
}

export function DataTable<TRow extends RowData>({
  table,
  emptyMessage,
  size,
}: {
  table: ReactTable<DataTableFeatures, TRow>;
  emptyMessage: string;
  // Optionnel, non renseigné par défaut : "lg" agrandit d'un cran les
  // en-têtes, le padding vertical des cellules et la pagination — écrit
  // pour la page "Mes exercices" (police trop petite, 2026-09-11) SANS
  // toucher au défaut de ce composant partagé par d'autres tables du
  // dashboard (utilisateurs, appels, arbitrage, etc.), qui restent
  // inchangées tant que ce prop n'est pas fourni.
  size?: "default" | "lg";
}) {
  const t = useTranslations("DataTable");
  const pageCount = Math.max(table.getPageCount(), 1);
  const currentPage = Math.min(table.state.pagination.pageIndex + 1, pageCount);
  const pageNumbers = getPageNumbers(currentPage, pageCount);
  const isLg = size === "lg";

  return (
    <div className="flex flex-1 flex-col gap-4">
      <Card className="overflow-hidden p-0">
        <Table className="**:data-[slot='table-cell']:px-4 **:data-[slot='table-head']:px-4">
          <TableHeader className="border-b border-sidebar-border bg-sidebar-accent/80 dark:bg-emerald-950/40 dark:border-emerald-900/40">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent hover:shadow-none">
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className={cn(
                      "py-3.5 font-bold tracking-wider text-sidebar-accent-foreground dark:text-emerald-400 uppercase",
                      isLg ? "text-base" : "text-sm",
                    )}
                  >
                    {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>

          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer border-b transition-all duration-150 hover:bg-emerald-800/10 hover:shadow-[inset_3px_0_0_0_var(--sidebar-primary)] dark:hover:bg-emerald-500/15"
                  data-state={table.state.rowSelection[row.id] && "selected"}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={cn(
                        "px-4 align-middle text-base font-medium text-slate-800 dark:text-zinc-200",
                        // Padding vertical remonté avec size="lg" : garde un
                        // espacement propre entre les lignes une fois le
                        // contenu des cellules agrandi (chaque colonne fixe
                        // sa propre taille de texte, cf. exercises-columns.tsx).
                        isLg ? "py-5" : "py-4",
                      )}
                    >
                      <table.FlexRender cell={cell} />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={table.getVisibleLeafColumns().length}
                  className="h-28 text-center text-sm font-medium text-slate-500 dark:text-zinc-400"
                >
                  {emptyMessage}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      <div className="flex items-center justify-end px-2 pt-1">
        <Pagination className="mx-0 w-auto justify-start md:justify-end">
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                text={t("previous")}
                className={cn(isLg && "text-base", !table.getCanPreviousPage() && "pointer-events-none opacity-50")}
                onClick={(event) => {
                  preventPaginationNavigation(event);
                  table.previousPage();
                }}
              />
            </PaginationItem>
            {pageNumbers[0] > 1 ? (
              <PaginationItem>
                <PaginationEllipsis />
              </PaginationItem>
            ) : null}
            {pageNumbers.map((pageNumber) => (
              <PaginationItem key={`page-${pageNumber}`}>
                <PaginationLink
                  href="#"
                  isActive={table.state.pagination.pageIndex === pageNumber - 1}
                  className={cn(
                    isLg && "text-base",
                    table.state.pagination.pageIndex === pageNumber - 1 &&
                      "bg-primary font-bold text-primary-foreground shadow-2xs hover:bg-primary/90 hover:text-primary-foreground",
                  )}
                  onClick={(event) => {
                    preventPaginationNavigation(event);
                    table.setPageIndex(pageNumber - 1);
                  }}
                >
                  {pageNumber}
                </PaginationLink>
              </PaginationItem>
            ))}
            {pageNumbers[pageNumbers.length - 1] < pageCount ? (
              <PaginationItem>
                <PaginationEllipsis />
              </PaginationItem>
            ) : null}
            <PaginationItem>
              <PaginationNext
                href="#"
                text={t("next")}
                className={cn(isLg && "text-base", !table.getCanNextPage() && "pointer-events-none opacity-50")}
                onClick={(event) => {
                  preventPaginationNavigation(event);
                  table.nextPage();
                }}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </div>
    </div>
  );
}

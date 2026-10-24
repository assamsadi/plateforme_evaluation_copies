import { Skeleton } from "@/components/ui/skeleton";
import { TableCell, TableRow } from "@/components/ui/table";

/** Ligne de chargement générique pour DataTable — un Skeleton par colonne visible. */
export function DataTableRowSkeleton({ columnCount }: { columnCount: number }) {
  return (
    <TableRow className="hover:bg-transparent hover:shadow-none">
      {Array.from({ length: columnCount }, (_, index) => (
        <TableCell key={index} className="px-4 py-3">
          <Skeleton className="h-4 w-full max-w-32" />
        </TableCell>
      ))}
    </TableRow>
  );
}

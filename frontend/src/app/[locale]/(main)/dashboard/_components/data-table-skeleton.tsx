import { Card } from "@/components/ui/card";
import { Table, TableBody } from "@/components/ui/table";

import { DataTableRowSkeleton } from "./data-table-row-skeleton";

/**
 * Écran de chargement pour une page listant des données via DataTable —
 * pas de <table> réelle disponible avant l'arrivée des données (aucune
 * instance TanStack table à ce stade), donc un gabarit de lignes
 * générique plutôt qu'un rendu lié aux colonnes définitives.
 */
export function DataTableSkeleton({ columnCount = 5, rowCount = 6 }: { columnCount?: number; rowCount?: number }) {
  return (
    <Card className="overflow-hidden p-0">
      <Table>
        <TableBody>
          {Array.from({ length: rowCount }, (_, index) => (
            <DataTableRowSkeleton key={index} columnCount={columnCount} />
          ))}
        </TableBody>
      </Table>
    </Card>
  );
}

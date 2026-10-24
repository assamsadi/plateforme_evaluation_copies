import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** Même grille que KpiCards, gabarits de chargement — évite le saut de mise en page. */
export function KpiCardsSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4.5 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }, (_, index) => (
        <Card key={index} className="relative overflow-hidden">
          <div className="absolute inset-x-0 top-0 h-1 bg-muted" />
          <CardHeader className="flex flex-row items-center justify-between px-4.5 pt-4 pb-1.5">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="size-9 rounded-xl" />
          </CardHeader>
          <CardContent className="px-4.5 pb-4">
            <div className="flex items-baseline justify-between">
              <Skeleton className="h-8 w-16" />
              <Skeleton className="h-4 w-14 rounded-md" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

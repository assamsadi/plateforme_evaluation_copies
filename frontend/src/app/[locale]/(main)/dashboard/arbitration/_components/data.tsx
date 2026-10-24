import type { StatusTone } from "@/components/ui/status-badge";
import type { IncidentStatusValue } from "@/lib/professor-api";

export const incidentStatusTone: Record<IncidentStatusValue, StatusTone> = {
  pending: "warning",
  resolved: "success",
};

export const incidentResolutionValues = [
  "justified_absence",
  "retry_granted",
  "deadline_extended",
  "rejected",
] as const;

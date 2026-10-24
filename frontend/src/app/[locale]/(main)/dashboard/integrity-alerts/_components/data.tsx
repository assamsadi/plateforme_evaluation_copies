import type { StatusTone } from "@/components/ui/status-badge";
import type { IntegrityAlertStatus } from "@/lib/admin-api";

export const statusTone: Record<IntegrityAlertStatus, StatusTone> = {
  pending: "warning",
  under_review: "info",
  confirmed: "danger",
  dismissed: "neutral",
};

export const resolvableStatuses: IntegrityAlertStatus[] = ["under_review", "confirmed", "dismissed"];

export const actionTakenValues = ["warning_issued", "grade_invalidated", "escalated", "no_action"] as const;

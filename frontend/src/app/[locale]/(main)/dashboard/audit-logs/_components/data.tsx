import type { StatusTone } from "@/components/ui/status-badge";
import type { AuditSeverity } from "@/lib/admin-api";

export const severityValues: AuditSeverity[] = ["info", "warning", "critical"];

export const severityTone: Record<AuditSeverity, StatusTone> = {
  info: "neutral",
  warning: "warning",
  critical: "danger",
};

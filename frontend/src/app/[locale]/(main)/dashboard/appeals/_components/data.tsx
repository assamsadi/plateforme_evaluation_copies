import type { StatusTone } from "@/components/ui/status-badge";
import type { AppealResolution, AppealStatus } from "@/lib/professor-api";

export const statusTone: Record<AppealStatus, StatusTone> = {
  pending: "warning",
  under_review: "info",
  resolved: "success",
};

export const resolutionValues: AppealResolution[] = ["grade_upheld", "grade_revised", "partial_revision"];

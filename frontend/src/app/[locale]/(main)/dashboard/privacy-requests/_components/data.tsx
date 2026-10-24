import type { StatusTone } from "@/components/ui/status-badge";
import type { PrivacyRequestStatus, PrivacyRequestType } from "@/lib/admin-api";

export const statusTone: Record<PrivacyRequestStatus, StatusTone> = {
  pending: "warning",
  in_progress: "info",
  completed: "success",
  rejected: "danger",
};

export const requestTypeValues: PrivacyRequestType[] = [
  "access_export",
  "erasure",
  "rectification",
  "restriction",
  "objection",
];

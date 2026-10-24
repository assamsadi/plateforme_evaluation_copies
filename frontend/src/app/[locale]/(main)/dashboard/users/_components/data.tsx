export type UserRole = "student" | "professor" | "admin";

export type UserRow = {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: UserRole;
  isActive: boolean;
};

export const roleValues: UserRole[] = ["student", "professor", "admin"];

// roleBadgeClass/statusMeta retirés — remplacés par StatusBadge (tone
// "neutral" pour les rôles, "success"/"danger" pour actif/désactivé),
// cf. unification design system (plus de couleur libre par rôle).

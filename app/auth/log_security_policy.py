"""
Politique de sécurité et d'habilitation pour la consultation des AgentDecisionLog.

Applique la règle de sécurité renforcée de la section 17 du document de référence :
- En statut DRAFT : accès EXCLUSIF au professeur créateur (created_by_professor_id).
  Même un administrateur est rejeté afin d'éviter tout risque de fuite d'épreuve non publiée.
- Après publication (PUBLISHED_AS_EXAM, PUBLISHED_AS_HOMEWORK, ARCHIVED_IN_LIBRARY) :
  accès autorisé au professeur créateur ET aux administrateurs (Admin) pour audit/litige.
  Rejeté pour tous les autres utilisateurs (étudiants, professeurs tiers).
"""
import uuid
from app.core.exceptions import ForbiddenError
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.identity.user import User, UserRole, Admin


def authorize_agent_log_access(user: User, exercise: Exercise) -> None:
    """
    Vérifie les habilitations d'accès aux logs de décision IA d'un exercice.
    Lève ForbiddenError si l'accès est refusé.
    """
    is_owner = (exercise.created_by_professor_id == user.id)
    is_admin = (
        isinstance(user, Admin) or getattr(user, "role", None) == UserRole.ADMIN
    )

    # 1. Cas DRAFT (Exercice non publié) : strictement restreint au créateur
    if exercise.status == ExerciseStatus.DRAFT:
        if not is_owner:
            raise ForbiddenError(
                "L'accès aux logs d'un exercice non publié (DRAFT) est strictement réservé au professeur créateur."
            )
        return

    # 2. Cas Publié / Archivé : créateur OU admin
    if not (is_owner or is_admin):
        raise ForbiddenError(
            "Accès refusé aux logs de décision IA pour cet exercice."
        )

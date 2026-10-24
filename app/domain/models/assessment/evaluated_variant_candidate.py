"""
EvaluatedVariantCandidate = garde-fou anti-boucle métier pour le déclencheur
à la demande (2.2) de Solution_Variant_Generation_Agent (cf. audit
Solution_Variant_Generation_Agent §2.2/§6, "Actions attendues").

Quand Comparative_Evaluation_Agent (pas encore construit) transmet une
méthode candidate d'étudiant, on ne redéclenche JAMAIS l'agent sur une
méthode déjà évaluée pour la même question — identifiée par sa STRUCTURE
(step_type + concept_tags, cf. structural_signature), jamais par le texte
exact, deux formulations différentes d'une même démarche doivent matcher.

Une seule ligne par (question_id, structural_signature) : la première
évaluation fait foi, la décision est réutilisée telle quelle ensuite.
Immuable une fois créée (CreatedAtOnlyMixin) — même principe qu'AgentDecisionLog,
une décision de garde-fou ne se réécrit pas après coup.
"""
import uuid
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import CreatedAtOnlyMixin, UUIDPKMixin


class CandidateDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EvaluatedVariantCandidate(Base, UUIDPKMixin, CreatedAtOnlyMixin):
    __tablename__ = "evaluated_variant_candidates"
    __table_args__ = (
        UniqueConstraint("question_id", "structural_signature", name="uq_evaluated_candidate_question_signature"),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=False
    )

    # sha256 hex sur la séquence de step_type + les concept_tags triés —
    # jamais un hash du texte brut (cf. docstring module).
    structural_signature: Mapped[str] = mapped_column(String(64), nullable=False)

    decision: Mapped[CandidateDecision] = mapped_column(
        PgEnum(CandidateDecision, name="candidate_decision"), nullable=False
    )

    # Rempli seulement si decision == ACCEPTED.
    resulting_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("solution_variants.id"), nullable=True
    )

    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

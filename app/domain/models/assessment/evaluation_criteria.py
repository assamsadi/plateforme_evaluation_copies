"""
EvaluationCriteria = le détail de la notation d'une Evaluation.

Deux familles de lignes coexistent pour une même Evaluation (Phase 4/4,
Pedagogical_Evaluation_Agent — invariant APPLICATIF, pas une contrainte SQL) :
  - Lignes CLASSIQUES (héritage) : criterion_id renseigné (référence l'id du
    critère DANS le JSON Bareme.criteria — pas une vraie FK SQL, une
    corrélation logique), competency_code=None.
  - Lignes COMPÉTENCE (nouvelle granularité, une par compétence C2PCT
    RÉELLEMENT mobilisée sur la question — jamais une par sous-question,
    trop fin pour un enregistrement persisté de note) : competency_code
    renseigné, criterion_id=None. points_awarded = points_competence
    (Pedagogical_Evaluation_Agent). subquestion_detail porte le détail brut
    (quelles sous-questions couvertes, quel taux) pour ne pas perdre la
    traçabilité fine sans multiplier les lignes en base — ex.
    {"subquestions": [{"subquestion_id": "1.1", "addressed": true,
    "is_correct": true, "source": "new_llm_judgment"}, ...],
    "covered_count": 5, "successful_count": 4, "success_rate": 0.8}.
  Exactement un des deux (criterion_id XOR competency_code) par ligne.
"""
import uuid
from decimal import Decimal

from sqlalchemy import Enum as PgEnum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class EvaluationCriteria(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "evaluation_criteria"
    # Invariant XOR (criterion_id / competency_code) — APPLICATIF, pas une
    # contrainte SQL (validé ainsi) : appliqué côté EvaluationService, pas
    # ici, pour rester simple (cf. docstring module).

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evaluations.id"), nullable=False
    )
    # nullable (2026-09-06) : une question C2PCT-native (Question.
    # subquestion_points, jamais de ligne Bareme) n'a tout simplement aucun
    # id à référencer ici — bug réel corrigé (uuid.UUID(None) plantait dans
    # evaluation_node.py dès qu'une évaluation atteignait ce cas, cf. son
    # docstring). Jamais lu ailleurs dans le code (grep confirmé) : purement
    # informatif pour une ligne "classique" (Bareme.criteria), toujours None
    # pour une ligne "compétence" C2PCT.
    bareme_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("baremes.id"), nullable=True
    )
    # Lignes classiques uniquement — correspond à l'id du critère dans
    # Bareme.criteria (JSON). None sur une ligne compétence.
    criterion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    points_awarded: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 4/4 — lignes compétence uniquement. None sur une ligne classique.
    competency_code: Mapped[C2PCTSkillCode | None] = mapped_column(
        PgEnum(C2PCTSkillCode, name="c2pct_skill_code"), nullable=True
    )
    # Phase 4/4 — lignes compétence uniquement, détail brut par sous-question
    # (cf. docstring module). None sur une ligne classique.
    subquestion_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
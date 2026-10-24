"""
Question = une sous-partie précise d'un Exercise (ex: "calculer le
périmètre", "calculer l'aire"). Niveau de granularité le plus fin pour
le barème, les variantes de solution, l'évaluation et le feedback
(§3 : tout est géré question par question, jamais globalement sur
toute la copie).

Compétences C2PCT mobilisées sur une question : jamais les 7 par défaut,
jamais une configuration par le prof — dérivées des sous-questions
officielles (c2pct_scaffold.py) réellement couvertes, cf. covered_
subquestions ci-dessous. QuestionC2PCTSkill a été supprimé (décision
actée en conversation), remplacé par ce mécanisme de sous-questions.
"""
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Sequence, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.domain.models.assessment.bareme import Bareme
    from app.domain.models.assessment.exercise import Exercise
    from app.domain.models.assessment.exercise_section import ExerciseSection


class Question(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("exercise_id", "order", name="uq_question_exercise_order"),
    )

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercise_sections.id", ondelete="SET NULL"), nullable=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    # Identifiant lisible séquentiel GLOBAL (audit "ids manquants") — cf.
    # commentaire Admin.admin_number pour le principe. Distinct de `order`
    # (position dans SON exercice uniquement, pas unique tous exercices
    # confondus — inutilisable seul pour retrouver une question précise).
    question_number: Mapped[int] = mapped_column(
        Integer, Sequence("question_number_seq"), unique=True, nullable=False
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_path: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # blob_path Azure (schéma/image), résolu en URL SAS à l'affichage
    # Phase 6 (Extraction_Verification_Agent, Phase 5A) — méthode/algorithme/
    # outil EXPLICITEMENT imposé par l'énoncé et/ou la correction. Propriété
    # de la question entière (stable avant même qu'une SolutionVariant
    # n'existe), pas d'une étape — toute variante future de cette question
    # doit la respecter également. None si aucun marqueur d'obligation.
    mandated_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Câblage workflow (câblage student_evaluation, Priorité 1) — id des
    # sous-questions officielles C2PCT (module c2pct_scaffold) que le
    # PROFESSEUR a réellement couvertes (Extraction_Verification_Agent,
    # Phase 2/4, QuestionVerificationResult.covered_subquestions) — même
    # principe que mandated_method ci-dessus : propriété de la question
    # entière, jamais devinée. Liste vide par défaut, jamais un total
    # théorique substitué à une couverture absente. Consommé par
    # comparative_evaluation_node pour construire EvaluationRequest.
    covered_subquestions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Chantier barème C2PCT natif — Cas 0 (prioritaire sur le calcul de
    # répartition proportionnelle de Pedagogical_Evaluation_Agent) : points
    # donnés DIRECTEMENT par le professeur pour une sous-question C2PCT
    # (clé = id de sous-question, ex. "1.1" ; valeur = points, stockée en
    # texte pour une désérialisation Decimal exacte, jamais un float JSON).
    # Nullable (contrairement à covered_subquestions) : None = aucun barème
    # détaillé par sous-question trouvé pour cette question, distinct d'un
    # dict vide qui n'est jamais produit (cf. Extraction_Verification_Agent.
    # _extract_subquestion_points — n'ajoute une question au résultat que
    # si au moins une sous-question y est chiffrée).
    subquestion_points: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 2026-08-29 (backlog_bugs_c2pct.md) — extraits VERBATIM vérifiés
    # déterministiquement (cf. Extraction_Verification_Agent._find_
    # verbatim_span) du texte de chaque sous-question officielle C2PCT
    # réellement couverte : [{"id": "1.1", "content": "..."}]. Additif,
    # jamais un remplacement de `statement` (qui reste le texte brut
    # complet, toujours consommé tel quel ailleurs, ex. VerifiableElement).
    # `official_title` n'est JAMAIS stocké ici — résolu à la lecture depuis
    # c2pct_scaffold (seule source de vérité). Nullable : None si covered_
    # subquestions est vide ou si l'extraction a échoué (best-effort, cf.
    # docstring de l'agent), jamais une liste vide ambiguë avec "aucune
    # sous-question couverte".
    subquestions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 2026-08-18 — règles générales du barème du professeur, non rattachées
    # à un critère/sous-question précis (Extraction_Verification_Agent,
    # QuestionVerificationResult.general_rules — fusion des 2 mécanismes
    # d'extraction, classique Cas 1/2 et C2PCT natif Cas 0, qui restent
    # séparés en amont). Même principe que covered_subquestions ci-dessus :
    # propriété de la question entière, jamais devinée, liste vide par
    # défaut. Consommé par comparative_evaluation_node pour construire
    # EvaluationRequest.general_rules — influence un VERDICT, jamais un
    # calcul de points direct (agent responsable inexistant).
    general_rules: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    exercise: Mapped["Exercise"] = relationship(back_populates="questions")
    section: Mapped["ExerciseSection | None"] = relationship(back_populates="questions")
    bareme: Mapped["Bareme | None"] = relationship(
        back_populates="question", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def max_points(self) -> Decimal:
        """
        Total noté de cette question, classique (Bareme.points) ou C2PCT
        natif (somme de subquestion_points) — les deux mécanismes restent
        mutuellement exclusifs par question (cf. docstring subquestion_points
        ci-dessus), jamais les deux à la fois.

        Centralisé ici (2026-09-06) après avoir trouvé la même faute
        `if q.bareme is not None` répétée dans au moins 4 endroits
        (evaluation_service.py x3, recommendation_service.py) — chacun
        excluait silencieusement toute question C2PCT-native au lieu de
        retomber sur son total réel, faussant des totaux/pourcentages
        affichés (0/0 sur "Mes résultats" pour un examen entièrement
        C2PCT-natif, cf. le bug qui a révélé ce pattern). Un seul point de
        vérité désormais — plus de risque de le ré-oublier à un 5e endroit.
        """
        if self.bareme is not None:
            return self.bareme.points
        return sum((Decimal(v) for v in (self.subquestion_points or {}).values()), Decimal("0"))
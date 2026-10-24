"""
ReasoningStep = une étape du graphe de raisonnement d'une SolutionVariant
(§2.2 CHAABI : "décomposer la solution en étapes logiques, identifier les
concepts clés, construire un graphe de raisonnement").

Le graphe est un vrai DAG (Directed Acyclic Graph) : une étape peut
dépendre de PLUSIEURS étapes précédentes (ex. une conclusion combinant
deux calculs indépendants) — d'où ReasoningStepDependency, une table
d'association séparée, plutôt qu'une simple FK auto-référencée qui ne
permettrait qu'un parent unique (chaîne/arbre, pas un vrai graphe).

related_competency_code relie chaque étape à la compétence C2PCT qu'elle
démontre principalement — donne à l'agent d'évaluation une explicabilité
directe ("l'étudiant a raté l'étape 3, qui relevait de la Structuration
Algorithmique"). Enum C2PCTSkillCode, pas de FK (table C2PCTCompetency
supprimée — le fichier .md est l'unique source de vérité du contenu).

Les algorithmes de traversée (détection de cycle, tri topologique pour
l'affichage linéaire) vivront dans reasoning_step_repository.py, jamais
ici — un modèle SQLAlchemy reste une pure structure de données, pas de
logique métier dessus (séparation des responsabilités, §7).
"""
import uuid
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class ReasoningStepType(StrEnum):
    GIVEN_DATA = "given_data"                    # donnée tirée de l'énoncé
    FORMULA_APPLICATION = "formula_application"  # application d'une formule/théorème
    COMPUTATION = "computation"                  # calcul numérique
    INTERMEDIATE_RESULT = "intermediate_result"  # résultat intermédiaire
    CONCLUSION = "conclusion"                    # résultat final de l'étape/variante
    CASE_SPLIT = "case_split"                    # raisonnement par cas disjoints (§2ter)
    INVERSE_SOLVE = "inverse_solve"               # contrainte posée puis inconnue isolée (§2ter)


class ReasoningStep(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "reasoning_steps"

    variant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("solution_variants.id"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)  # ordre d'affichage linéaire de secours
    step_type: Mapped[ReasoningStepType] = mapped_column(
        PgEnum(ReasoningStepType, name="reasoning_step_type"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)  # LaTeX si applicable

    # Ex: ["theoreme_steiner", "moment_inertie"]
    concept_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Ex: ["calculatrice", "table_de_moments"]
    tools_used: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    related_competency_code: Mapped[C2PCTSkillCode | None] = mapped_column(
        PgEnum(C2PCTSkillCode, name="c2pct_skill_code"), nullable=True
    )
    # Note: related_competency_name est positionné dynamiquement en mémoire
    # par le service pour ReasoningStepRead, pas comme colonne ORM.

    # Phase 6 (Extraction_Verification_Agent, Phases 3a/3b) — signaux par
    # étape sans colonne SQL dédiée : anomaly_detected, anomaly_justification,
    # case_group_id, recurrence_role, canonical_form, dimensional_check_result,
    # numeric_tolerance, criticality, source_span. Catch-all JSONB plutôt que
    # 9 colonnes typées — cohérent avec concept_tags/tools_used déjà en JSONB
    # sur cette même table, champs avant tout informatifs/traçables à ce
    # stade, pas interrogés individuellement. None si l'étape n'a produit
    # aucun de ces signaux.
    extraction_signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Versionnement & Auditabilité (Reasoning_Graph_Agent)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reasoning_steps.id"), nullable=True
    )




class ReasoningStepDependency(Base, UUIDPKMixin):
    """
    Arête du graphe : `step` dépend de `depends_on_step`. Pas de
    TimestampMixin ici — une simple arête n'a pas besoin d'historique
    propre, elle vit et meurt avec les étapes qu'elle relie.
    """
    __tablename__ = "reasoning_step_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "step_id", "depends_on_step_id", name="uq_reasoning_step_dependency"
        ),
    )

    step_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reasoning_steps.id"), nullable=False
    )
    depends_on_step_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reasoning_steps.id"), nullable=False
    )
"""
Repository SolutionVariant — racine d'agrégat couvrant SolutionVariant +
ReasoningStep + ReasoningStepDependency (le graphe de raisonnement).

get_reasoning_steps_ordered() utilise topological_sort() (Kahn,
graph_algorithms.py) pour l'affichage linéaire d'un graphe potentiellement
non-linéaire — le champ ReasoningStep.order sert de repli/tri secondaire
en cas d'égalité dans le graphe, pas de source de vérité principale.
"""
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepDependency
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantSource,
    VariantStatus,
)
from app.domain.repositories.graph_algorithms import topological_sort


class SolutionVariantRepositoryProtocol(Protocol):
    async def get_by_id(self, variant_id: uuid.UUID) -> SolutionVariant | None: ...
    async def list_by_question(self, question_id: uuid.UUID) -> list[SolutionVariant]: ...
    async def get_reasoning_steps_ordered(self, variant_id: uuid.UUID) -> list[ReasoningStep]: ...
    async def create_with_reasoning_graph(
        self,
        question_id: uuid.UUID,
        content: str,
        source: VariantSource,
        difficulty_level: VariantDifficulty,
        is_reference: bool,
        structured_content: dict | None,
        steps_data: list[dict],
    ) -> SolutionVariant: ...
    async def validate(
        self, variant_id: uuid.UUID, status: VariantStatus, professor_id: uuid.UUID, comment: str | None
    ) -> SolutionVariant | None: ...


class SQLAlchemySolutionVariantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, variant_id: uuid.UUID) -> SolutionVariant | None:
        return await self._session.get(SolutionVariant, variant_id)

    async def list_by_question(self, question_id: uuid.UUID) -> list[SolutionVariant]:
        result = await self._session.execute(
            select(SolutionVariant).where(SolutionVariant.question_id == question_id)
        )
        return list(result.scalars().all())

    async def get_reasoning_steps_ordered(self, variant_id: uuid.UUID) -> list[ReasoningStep]:
        """
        Charge toutes les étapes + arêtes en 2 requêtes (O(1) aller-retour
        DB, pas de N+1), construit le graphe en mémoire.

        Le tri de Kahn (topological_sort) sert UNIQUEMENT à valider
        l'absence de cycle (CyclicGraphError) et à résoudre depends_on_
        step_ids — jamais à ordonner le tableau retourné. Corrigé en test
        réel (validation professeur) : Kahn produit un ordre valide au sens
        du graphe (chaque étape après ses dépendances), mais PAS forcément
        la séquence narrative voulue — une étape sans dépendance autre que
        la toute première (ex. étape 5 ne dépendant que de l'étape 1) peut
        remonter arbitrairement tôt (constaté : 1, 5, 2, 3, 4, 6, 7 au lieu
        de 1..7), alors que ReasoningStep.order reflète déjà, tel que rédigé
        par Reasoning_Graph_Agent, l'ordre RÉEL de présentation du
        raisonnement par le professeur dans son document source (vérifié
        contre le PDF) — la seule séquence lisible pour une validation
        humaine. Trier par order ici ne casse aucun consommateur existant :
        comparative_evaluation_node.py rembarque déjà `order` explicitement
        dans chaque dict retourné, jamais l'ordre d'itération du tableau.
        """
        steps_result = await self._session.execute(
            select(ReasoningStep).where(ReasoningStep.variant_id == variant_id)
        )
        steps = list(steps_result.scalars().all())
        step_ids = [s.id for s in steps]

        deps_result = await self._session.execute(
            select(ReasoningStepDependency).where(
                ReasoningStepDependency.step_id.in_(step_ids)
            )
        )
        dependencies = list(deps_result.scalars().all())

        # graph[step_id] = [ids des étapes dont step_id dépend]
        graph: dict[str, list[str]] = {str(s.id): [] for s in steps}
        for dep in dependencies:
            graph[str(dep.step_id)].append(str(dep.depends_on_step_id))

        topological_sort(graph)  # lève CyclicGraphError si incohérent — résultat jamais utilisé, cf. docstring

        # depends_on_step_ids positionné dynamiquement (même pattern que
        # related_competency_name côté service, cf. sa docstring) — champ
        # REQUIS par ReasoningStepRead mais absent de la colonne ORM
        # (les dépendances vivent dans ReasoningStepDependency, une table
        # d'association séparée, cf. docstring du modèle). Sans ce champ,
        # ReasoningStepRead.model_validate() lève une ValidationError
        # ("Field required") sur CHAQUE étape — 500 systématique de
        # GET /solution-variants/{id}/reasoning-graph, constaté en test réel.
        for step in steps:
            step.depends_on_step_ids = [uuid.UUID(dep_id) for dep_id in graph[str(step.id)]]

        return sorted(steps, key=lambda s: s.order)

    async def create_with_reasoning_graph(
        self,
        question_id: uuid.UUID,
        content: str,
        source: VariantSource,
        difficulty_level: VariantDifficulty,
        is_reference: bool,
        structured_content: dict | None,
        steps_data: list[dict],
    ) -> SolutionVariant:
        """
        `steps_data` : liste de dicts déjà validés par
        solution_schemas.SolutionVariantCreate (cycle déjà vérifié côté
        Pydantic) — ex. :
            [{"step_ref": "s1", "order": 1, "step_type": ..., ...,
              "depends_on_refs": []},
             {"step_ref": "s2", "order": 2, ..., "depends_on_refs": ["s1"]}]

        Résout les step_ref temporaires en vrais UUID après insertion
        (cf. solution_schemas.py : les étapes n'ont pas encore d'id au
        moment de la requête, créées ensemble).
        """
        variant = SolutionVariant(
            question_id=question_id,
            content=content,
            structured_content=structured_content,
            is_reference=is_reference,
            source=source,
            difficulty_level=difficulty_level,
            status=VariantStatus.APPROVED if is_reference else VariantStatus.PENDING_VALIDATION,
        )
        self._session.add(variant)
        await self._session.flush()

        ref_to_id: dict[str, uuid.UUID] = {}
        for step_data in steps_data:
            step = ReasoningStep(
                variant_id=variant.id,
                order=step_data["order"],
                step_type=step_data["step_type"],
                description=step_data["description"],
                formula=step_data.get("formula"),
                concept_tags=step_data.get("concept_tags", []),
                tools_used=step_data.get("tools_used", []),
                related_competency_code=step_data.get("related_competency_code"),
                # Phase 6 — signaux Phases 3a/3b sans colonne dédiée (cf.
                # reasoning_step.py) ; None si l'appelant n'en fournit pas
                # (ex. Solution_Variant_Generation_Agent, hors périmètre ici).
                extraction_signals=step_data.get("extraction_signals"),
            )
            self._session.add(step)
            await self._session.flush()
            ref_to_id[step_data["step_ref"]] = step.id

        for step_data in steps_data:
            for dep_ref in step_data.get("depends_on_refs", []):
                dependency = ReasoningStepDependency(
                    step_id=ref_to_id[step_data["step_ref"]],
                    depends_on_step_id=ref_to_id[dep_ref],
                )
                self._session.add(dependency)

        await self._session.flush()
        return variant

    async def validate(
        self, variant_id: uuid.UUID, status: VariantStatus, professor_id: uuid.UUID, comment: str | None
    ) -> SolutionVariant | None:
        variant = await self.get_by_id(variant_id)
        if variant is None:
            return None
        variant.status = status
        variant.validated_by_professor_id = professor_id
        variant.review_comment = comment
        await self._session.flush()
        return variant
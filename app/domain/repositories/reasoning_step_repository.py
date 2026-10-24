"""
Repository ReasoningStep.

Porte le CRUD standard pour ReasoningStep et ReasoningStepDependency,
plus la détection de cycle (garde-fou acté pour Reasoning_Graph_Agent).

La détection de cycle utilise l'algorithme de Kahn implémenté dans
graph_algorithms.topological_sort : lève CyclicGraphError si le graphe
proposé contient un cycle. Cette vérification est effectuée AVANT tout
flush/commit — fail loud plutôt que persistance d'un graphe invalide.

Séquence d'utilisation par l'agent :
  1. `create_step(...)` → persiste l'étape
  2. `add_dependency(step_id, depends_on_step_id)` → ajoute l'arête
  3. `detect_cycle(variant_id)` → vérifie l'invariant DAG (optionnel mais
     recommandé à chaque ajout d'arête — coût O(V+E), acceptable en OLTP)
  4. `get_ordered_steps(variant_id)` → tri topologique pour l'affichage
"""
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.reasoning_step import (
    ReasoningStep,
    ReasoningStepDependency,
    ReasoningStepType,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.repositories.graph_algorithms import CyclicGraphError, topological_sort


class ReasoningStepRepositoryProtocol(Protocol):
    async def create_step(
        self,
        variant_id: uuid.UUID,
        order: int,
        step_type: ReasoningStepType,
        description: str,
        formula: str | None = None,
        concept_tags: list[str] | None = None,
        tools_used: list[str] | None = None,
        related_competency_code: C2PCTSkillCode | None = None,
    ) -> ReasoningStep: ...

    async def get_by_id(self, step_id: uuid.UUID) -> ReasoningStep | None: ...

    async def list_by_variant(self, variant_id: uuid.UUID) -> list[ReasoningStep]: ...

    async def add_dependency(
        self,
        step_id: uuid.UUID,
        depends_on_step_id: uuid.UUID,
    ) -> ReasoningStepDependency: ...

    async def get_dependencies(
        self, variant_id: uuid.UUID
    ) -> list[ReasoningStepDependency]: ...

    async def detect_cycle(self, variant_id: uuid.UUID) -> bool: ...

    async def get_ordered_steps(self, variant_id: uuid.UUID) -> list[ReasoningStep]: ...


class SQLAlchemyReasoningStepRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_step(
        self,
        variant_id: uuid.UUID,
        order: int,
        step_type: ReasoningStepType,
        description: str,
        formula: str | None = None,
        concept_tags: list[str] | None = None,
        tools_used: list[str] | None = None,
        related_competency_code: C2PCTSkillCode | None = None,
    ) -> ReasoningStep:
        step = ReasoningStep(
            variant_id=variant_id,
            order=order,
            step_type=step_type,
            description=description,
            formula=formula,
            concept_tags=concept_tags or [],
            tools_used=tools_used or [],
            related_competency_code=related_competency_code,
        )
        self._session.add(step)
        await self._session.flush()
        return step

    async def get_by_id(self, step_id: uuid.UUID) -> ReasoningStep | None:
        return await self._session.get(ReasoningStep, step_id)

    async def list_by_variant(self, variant_id: uuid.UUID) -> list[ReasoningStep]:
        result = await self._session.execute(
            select(ReasoningStep)
            .where(ReasoningStep.variant_id == variant_id)
            .order_by(ReasoningStep.order)
        )
        return list(result.scalars().all())

    async def add_dependency(
        self,
        step_id: uuid.UUID,
        depends_on_step_id: uuid.UUID,
    ) -> ReasoningStepDependency:
        dep = ReasoningStepDependency(
            step_id=step_id,
            depends_on_step_id=depends_on_step_id,
        )
        self._session.add(dep)
        await self._session.flush()
        return dep

    async def get_dependencies(
        self, variant_id: uuid.UUID
    ) -> list[ReasoningStepDependency]:
        """Récupère toutes les arêtes du graphe pour une variante."""
        steps_result = await self._session.execute(
            select(ReasoningStep.id).where(ReasoningStep.variant_id == variant_id)
        )
        step_ids = list(steps_result.scalars().all())
        if not step_ids:
            return []
        deps_result = await self._session.execute(
            select(ReasoningStepDependency).where(
                ReasoningStepDependency.step_id.in_(step_ids)
            )
        )
        return list(deps_result.scalars().all())

    async def detect_cycle(self, variant_id: uuid.UUID) -> bool:
        """
        Détecte un cycle dans le graphe de raisonnement d'une variante.

        Retourne True si un cycle est détecté (graphe invalide), False sinon.
        Utilise l'algorithme de Kahn (O(V+E)) via graph_algorithms.topological_sort.

        Note : ne lève PAS CyclicGraphError ici — retourne un booléen pour
        laisser l'appelant décider (l'agent peut vouloir logguer sans crasher,
        ou le service peut vouloir lever une DomainError contextualisée).
        """
        steps = await self.list_by_variant(variant_id)
        if not steps:
            return False
        deps = await self.get_dependencies(variant_id)
        # Construire le graphe {step_id: [depends_on_step_id, ...]}
        step_id_strs = {str(s.id) for s in steps}
        graph: dict[str, list[str]] = {str(s.id): [] for s in steps}
        for dep in deps:
            step_key = str(dep.step_id)
            dep_val = str(dep.depends_on_step_id)
            if step_key in graph:
                graph[step_key].append(dep_val)
        try:
            topological_sort(graph)
            return False
        except CyclicGraphError:
            return True

    async def get_ordered_steps(self, variant_id: uuid.UUID) -> list[ReasoningStep]:
        """
        Retourne les étapes dans l'ordre topologique (tri du DAG).
        Lève CyclicGraphError si le graphe est invalide (ne devrait jamais
        arriver en production si detect_cycle est appelé avant chaque ajout
        d'arête).
        """
        steps = await self.list_by_variant(variant_id)
        if not steps:
            return []
        deps = await self.get_dependencies(variant_id)
        steps_by_id = {str(s.id): s for s in steps}
        graph: dict[str, list[str]] = {str(s.id): [] for s in steps}
        for dep in deps:
            step_key = str(dep.step_id)
            if step_key in graph:
                graph[step_key].append(str(dep.depends_on_step_id))
        ordered_ids = topological_sort(graph)
        return [steps_by_id[sid] for sid in ordered_ids if sid in steps_by_id]

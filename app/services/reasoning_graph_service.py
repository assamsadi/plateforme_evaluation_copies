"""
Service d'orchestration pour Reasoning_Graph_Agent.

Gère le cycle de vie, la persistance transactionnelle, la parallélisation (asyncio.gather)
et l'invalidation en cascade scopée par question.

Rattrapage section 10ter — Mécanisme few-shot par récupération (RAG) :
  Avant de persister une nouvelle ClarificationRequest, le service cherche dans la
  table des clarifications déjà résolues si un cas similaire existe (similarité cosinus
  via app.repositories.rag_repository). Si oui, la réponse historique est appliquée
  directement et tracée dans AgentDecisionLog avec la mention RAG. Si non, la
  clarification est persistée normalement (comportement inchangé).

  Le RAG est une optimisation, pas un prérequis : si sentence-transformers est
  indisponible ou si pgvector n'est pas activé, le mécanisme est silencieusement
  désactivé et le système continue à fonctionner normalement (clarifications HITL).
"""
import asyncio
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import ClarificationRequest
from app.agents.Reasoning_Graph_Agent import ExistingStepInput, ReasoningGraphAgent, ReasoningGraphReport
from app.agents.reasoning_graph_exceptions import (
    ExerciseAlreadyPublishedError,
    ReasoningGraphError,
    VariantNotFoundError,
)
from app.core.embeddings import embed_text
from app.core.config import settings
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationStatus,
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepDependency
from app.domain.models.assessment.solution_variant import SolutionVariant, VariantStatus
from app.domain.models.system_infrastructure.agent_decision_log import AgentDecisionLog
from app.domain.schemas.reasoning_graph_schemas import (
    QuestionCascadeInvalidationReport,
    ReasoningGraphRead,
)
from app.repositories.rag_repository import search_similar

logger = logging.getLogger(__name__)


class ReasoningGraphService:
    """Service d'orchestration pour Reasoning_Graph_Agent."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._agent = ReasoningGraphAgent()

    async def build_graph_for_variant(
        self,
        variant_id: uuid.UUID,
        trace_id: str | None = None,
        allow_post_publication: bool = False,
    ) -> ReasoningGraphRead:
        """
        Construit et persiste le graphe de raisonnement d'une variante.
        Gère le versionnement et la persistance transactionnelle complète.

        allow_post_publication : Reasoning_Graph_Agent lui-même n'a pas de
        notion de déclencheur (toujours proactif, cf. reasoning_graph_node) —
        le blocage post-publication reste donc la valeur par défaut partout
        où cette méthode est appelée depuis le flow exercise_setup. Seul
        SolutionVariantGenerationService passe True depuis ses parcours 2.2
        (à la demande) et 2.3 (guidé), qui sont l'exception documentée et
        scopée à la republication (cf. audit Solution_Variant_Generation_Agent
        §9 dernier point) : jamais depuis une régénération proactive (2.1).
        """
        # 1. Charger la variante, la question et l'exercice
        variant = await self._session.get(SolutionVariant, variant_id)
        if variant is None:
            raise VariantNotFoundError(variant_id)

        question = await self._session.get(Question, variant.question_id)
        if question is None:
            raise ReasoningGraphError(f"Question {variant.question_id} introuvable pour la variante {variant_id}")

        exercise = await self._session.get(Exercise, question.exercise_id)
        if exercise is None:
            raise ReasoningGraphError(f"Exercice {question.exercise_id} introuvable")

        # Précondition : l'exercice ne doit pas être publié (doit être en DRAFT),
        # sauf exception explicite (cf. docstring allow_post_publication).
        if exercise.status != ExerciseStatus.DRAFT and not allow_post_publication:
            raise ExerciseAlreadyPublishedError(exercise.id, exercise.status.value)


        # Précondition : les étapes déjà décomposées et persistées par
        # Extraction_Verification_Agent (Agent 4) — jamais un texte brut à
        # reparser indépendamment (cf. docstring module Reasoning_Graph_Agent
        # v2 : la v1 reparsait le texte source, ce qui supersédait/perdait
        # canonical_form/dimensional_check_result déjà calculés par Agent 4).
        existing_steps_result = await self._session.execute(
            select(ReasoningStep).where(ReasoningStep.variant_id == variant_id)
        )
        existing_steps = sorted(existing_steps_result.scalars().all(), key=lambda s: s.order)
        if not existing_steps:
            raise ReasoningGraphError(
                f"Aucune étape décomposée trouvée pour la variante {variant_id} — "
                f"Extraction_Verification_Agent doit s'exécuter avant Reasoning_Graph_Agent."
            )

        steps_input = [
            ExistingStepInput(
                step_id=str(s.id),
                order=s.order,
                step_type=s.step_type,
                description=s.description,
                formula=s.formula,
                source_span=(s.extraction_signals or {}).get("source_span", ""),
            )
            for s in existing_steps
        ]

        trace_id = trace_id or str(uuid.uuid4())
        context = AgentExecutionContext(
            trace_id=trace_id,
            flow_type="exercise_setup",
            exercise_id=exercise.id,
        )

        # 2. Exécution de l'agent AI — enrichissement, jamais une redécouverte
        domain_type = getattr(question, "question_domain_type", "open_ended")
        report: ReasoningGraphReport = await self._agent.execute(
            variant_id=variant_id,
            steps=steps_input,
            question_domain_type=str(domain_type),
            context=context,
        )

        # 3. Mise à jour EN PLACE des ReasoningStep déjà persistés — jamais
        # une nouvelle version : ce sont les MÊMES étapes (step_ref == str(id)
        # d'un ReasoningStep existant), seulement enrichies. extraction_signals
        # est FUSIONNÉ (jamais remplacé) pour ne pas écraser canonical_form/
        # dimensional_check_result/anomaly_detected déjà calculés par Agent 4.
        steps_by_id = {str(s.id): s for s in existing_steps}
        for step_out in report.steps:
            db_step = steps_by_id.get(step_out.step_ref)
            if db_step is None:
                continue  # ne devrait jamais arriver : step_ref vient de existing_steps lui-même

            db_step.concept_tags = step_out.concept_tags
            db_step.tools_used = step_out.tools_used
            if step_out.competency_weights:
                top_item = max(step_out.competency_weights, key=lambda cw: cw.weight)
                if top_item.weight > 0.0:
                    db_step.related_competency_code = top_item.code

            weights_signals = [
                {"code": cw.code.value, "weight": cw.weight}
                for cw in step_out.competency_weights
            ]
            merged_signals = dict(db_step.extraction_signals or {})
            merged_signals.update({
                "competency_weights": weights_signals,
                "is_core_step": step_out.is_core_step,
                "downstream_step_refs": step_out.downstream_step_refs,
            })
            db_step.extraction_signals = merged_signals

        # Remplace la chaîne linéaire naïve posée par Agent 4
        # (_persist_reasoning_graph) par les vraies arêtes DAG inférées ici.
        await self._session.execute(
            delete(ReasoningStepDependency).where(
                ReasoningStepDependency.step_id.in_([s.id for s in existing_steps])
            )
        )
        for step_out in report.steps:
            curr_id = uuid.UUID(step_out.step_ref)
            for dep_ref in step_out.depends_on_refs:
                if dep_ref in steps_by_id:
                    self._session.add(ReasoningStepDependency(
                        step_id=curr_id,
                        depends_on_step_id=uuid.UUID(dep_ref),
                    ))
        await self._session.flush()

        # 4. Traitement des clarifications : court-circuit RAG d'abord, sinon persistance
        blocking_count = 0
        rag_resolved, clarifs_to_persist = await self._rag_shortcircuit_clarifications(
            clarifications=report.clarifications,
            variant_id=variant_id,
            exercise_id=exercise.id,
        )

        for clarif in clarifs_to_persist:
            if clarif.severity.value == "blocking":
                blocking_count += 1
            clarif_entity = ReasoningClarificationRequest(
                variant_id=variant_id,
                unclear_content=clarif.agent_question,
                agent_question=clarif.agent_question,
                proposed_answer=clarif.proposed_answer,
                severity=clarif.severity,
            )
            self._session.add(clarif_entity)

        # 5. Journaliser l'exécution dans AgentDecisionLog
        log_entry = AgentDecisionLog(
            agent_name=ReasoningGraphAgent.AGENT_NAME,
            related_entity_type="SolutionVariant",
            related_entity_id=variant_id,
            justification=(
                f"Graphe enrichi avec {len(report.steps)} étapes "
                f"(confiance: {report.construction_confidence:.2f})"
                + (f". {rag_resolved} clarification(s) résolue(s) par RAG few-shot." if rag_resolved else "")
            ),
            confidence_score=Decimal(str(round(report.construction_confidence, 3))),
            model_version=report.model_version or "groq:llama-3.3-70b",
            thread_id=exercise.id,
            output_summary=json.dumps({
                "step_count": len(report.steps),
                "construction_confidence": report.construction_confidence,
                "clarification_count": len(report.clarifications),
                "rag_resolved_count": rag_resolved,
                "is_valid_dag": report.is_valid_dag,
            }),
        )
        self._session.add(log_entry)
        await self._session.flush()


        return ReasoningGraphRead(
            variant_id=variant_id,
            construction_confidence=report.construction_confidence,
            is_valid_dag=report.is_valid_dag,
            step_count=len(report.steps),
            blocking_clarification_count=blocking_count,
            model_version=report.model_version,
        )

    async def _rag_shortcircuit_clarifications(
        self,
        clarifications: list[ClarificationRequest],
        variant_id: uuid.UUID,
        exercise_id: uuid.UUID,
    ) -> tuple[int, list[ClarificationRequest]]:
        """
        Pour chaque clarification candidate, cherche un cas similaire déjà résolu par RAG.

        Retourne:
          - rag_resolved_count : nombre de clarifications résolues par court-circuit RAG.
          - remaining : clarifications restantes à persister normalement.

        Si le RAG est indisponible (sentence-transformers absent ou pgvector non installé),
        retourne (0, clarifications) sans modifier le comportement de l'appelant.
        """
        if not clarifications:
            return 0, []

        rag_resolved_count = 0
        remaining: list[ClarificationRequest] = []
        similarity_threshold = getattr(settings, "RAG_SIMILARITY_THRESHOLD", 0.85)

        for clarif in clarifications:
            embedding = embed_text(clarif.agent_question)
            if embedding is None:
                # RAG indisponible pour cette clarification → comportement normal
                remaining.append(clarif)
                continue

            try:
                matches = await search_similar(
                    session=self._session,
                    embedding_query=embedding,
                    table_name="reasoning_clarification_requests",
                    embedding_column="embedding",
                    id_column="id",
                    payload_columns=["professor_answer", "agent_question", "answered_at"],
                    filter_clauses="status = 'ANSWERED' AND professor_answer IS NOT NULL",
                    top_k=1,
                    similarity_threshold=similarity_threshold,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[RAG] Erreur lors de la recherche few-shot : %s", exc)
                remaining.append(clarif)
                continue

            if not matches:
                remaining.append(clarif)
                continue

            # Correspondance trouvée — court-circuit RAG
            best = matches[0]
            professor_answer = best.payload.get("professor_answer", "")
            answered_at = best.payload.get("answered_at")
            rag_resolved_count += 1

            logger.info(
                "[RAG] Clarification court-circuitée par récupération few-shot "
                "(similarité=%.3f, cas du %s) : %s",
                best.similarity, answered_at, clarif.agent_question[:80],
            )

            # Trace explicite dans AgentDecisionLog : origine RAG, jamais un nouveau jugement
            rag_log = AgentDecisionLog(
                agent_name=ReasoningGraphAgent.AGENT_NAME,
                related_entity_type="SolutionVariant",
                related_entity_id=variant_id,
                justification=(
                    f"[RAG few-shot] Clarification résolue par récupération d'un cas similaire "
                    f"déjà tranché (similarité cosinus={best.similarity:.3f}, "
                    f"cas résolu le {answered_at}). "
                    f"Réponse appliquée automatiquement : {professor_answer[:200]}"
                ),
                confidence_score=Decimal(str(round(best.similarity, 3))),
                model_version="rag:all-MiniLM-L6-v2",
                thread_id=exercise_id,
                output_summary=json.dumps({
                    "rag_source_id": str(best.id),
                    "rag_similarity": best.similarity,
                    "clarification_question": clarif.agent_question,
                    "applied_answer": professor_answer,
                }),
            )
            self._session.add(rag_log)

        return rag_resolved_count, remaining

    async def index_clarification_embedding(
        self,
        clarification_id: uuid.UUID,
    ) -> None:
        """
        Calcule et persiste l'embedding d'une clarification résolue.

        Doit être appelé immédiatement après qu'un professeur répond à une
        clarification (status → ANSWERED). Cela rend le cas immédiatement
        retrouvable par les futurs appels RAG few-shot.

        Si l'embedding est indisponible (sentence-transformers absent), la méthode
        retourne silencieusement sans erreur : la clarification reste consultable
        en texte brut, mais ne sera pas trouvable par similarité vectorielle.
        """
        clarif = await self._session.get(ReasoningClarificationRequest, clarification_id)
        if clarif is None:
            logger.warning(
                "[RAG] index_clarification_embedding : clarification %s introuvable.",
                clarification_id,
            )
            return

        if clarif.status != ClarificationStatus.ANSWERED:
            logger.debug(
                "[RAG] Clarification %s n'est pas encore résolue (status=%s). Indexation ignorée.",
                clarification_id, clarif.status,
            )
            return

        # Texte à vectoriser : la question posée par l'agent (pas la réponse — on
        # cherche à retrouver par similarité de question, pas de réponse).
        embedding = embed_text(clarif.agent_question)
        if embedding is None:
            logger.debug(
                "[RAG] Embedding indisponible, clarification %s non indexée.",
                clarification_id,
            )
            return

        # Câblage Priorité 2 — embedding est désormais Vector(384) natif
        # (pgvector.sqlalchemy.Vector), le type Python attendu est
        # list[float] directement, jamais une chaîne JSON sérialisée (testé
        # empiriquement : json.dumps() provoque un DatatypeMismatchError
        # côté asyncpg contre une colonne vector).
        clarif.embedding = embedding
        await self._session.flush()
        logger.info(
            "[RAG] Clarification %s indexée avec succès (dim=%d).",
            clarification_id, len(embedding),
        )

    async def build_graphs_for_variants_parallel(
        self,
        variant_ids: list[uuid.UUID],
        max_concurrency: int = 4,
        trace_id: str | None = None,
    ) -> list[ReasoningGraphRead | Exception]:
        """
        Exécute la construction de graphes pour N variantes en parallèle.
        Utilise asyncio.Semaphore pour respecter les rate limits.
        """
        sem = asyncio.Semaphore(max_concurrency)

        async def _worker(vid: uuid.UUID):
            async with sem:
                return await self.build_graph_for_variant(vid, trace_id=trace_id)

        tasks = [_worker(vid) for vid in variant_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return list(results)

    async def invalidate_cascade_for_question(
        self,
        question_id: uuid.UUID,
    ) -> QuestionCascadeInvalidationReport:
        """
        Invalide les variantes dérivées (non-référence) rattachées à une question
        lorsque la solution de référence du professeur est modifiée.
        """
        question = await self._session.get(Question, question_id)
        if question is None:
            raise ReasoningGraphError(f"Question {question_id} introuvable")

        variants_result = await self._session.execute(
            select(SolutionVariant).where(SolutionVariant.question_id == question_id)
        )
        variants = list(variants_result.scalars().all())

        invalidated_ids: list[uuid.UUID] = []
        for v in variants:
            if not v.is_reference:
                v.status = VariantStatus.PENDING_VALIDATION
                v.review_comment = (
                    f"Invalidé suite à la modification de la solution de référence "
                    f"pour la question N°{question.order}. Une régénération du graphe est requise avant publication."
                )
                invalidated_ids.append(v.id)

        await self._session.flush()

        msg = (
            f"La modification de la solution de référence pour la question N°{question.order} "
            f"a invalidé {len(invalidated_ids)} variante(s) dérivée(s). Leurs graphes doivent être régénérés."
            if invalidated_ids
            else f"Aucune variante dérivée à invalider pour la question N°{question.order}."
        )

        return QuestionCascadeInvalidationReport(
            question_id=question_id,
            question_order=question.order,
            invalidated_variant_ids=invalidated_ids,
            professor_message=msg,
        )

"""
Service d'orchestration pour Solution_Variant_Generation_Agent.

Gère le cycle de vie, la persistance transactionnelle, la délégation à ReasoningGraphService,
la parallélisation entre questions et le rapport de revue professeur (4 actions).
"""
import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import ExtractionVerificationAgent, QuestionInput
from app.agents.solution_variant_generation_exceptions import (
    ExerciseAlreadyPublishedError,
    SolutionVariantGenerationError,
)
from app.agents.Solution_Variant_Generation_Agent import SolutionVariantGenerationAgent
from app.core.exceptions import NotExerciseOwnerError, QuestionNotFoundError
from app.domain.models.assessment.evaluated_variant_candidate import (
    CandidateDecision,
    EvaluatedVariantCandidate,
)
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_step import (
    ReasoningStep,
    ReasoningStepDependency,
    ReasoningStepType,
)
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantStatus,
    VariantSource,
)
from app.domain.models.assessment.submission import Submission
from app.domain.models.system_infrastructure.agent_decision_log import AgentDecisionLog
from app.domain.models.system_infrastructure.notification import (
    Notification,
    NotificationChannel,
    NotificationPriority,
)
from app.domain.schemas.solution_variant_generation_schemas import (
    ReferenceStepContext,
    RetroactiveEquityReport,
    SolutionVariantSummaryRead,
    VariantGenerationAgentReport,
    VariantReviewAction,
    VariantReviewRequest,
)
from app.services.extraction_verification_service import ExtractionVerificationService
from app.services.reasoning_graph_service import ReasoningGraphService

logger = logging.getLogger(__name__)


def compute_structural_signature(steps: list[dict], concept_tags: list[str]) -> str:
    """
    Signature STRUCTURELLE (jamais textuelle) d'une méthode candidate, pour
    le garde-fou anti-boucle du déclencheur à la demande (2.2, cf. audit §1b) :
    deux formulations différentes d'une même démarche doivent produire la
    même signature. Basée sur la séquence ordonnée de step_type + l'ensemble
    trié des concept_tags — même principe de comparaison que
    SolutionVariantGenerationAgent._compute_structural_distinction.
    """
    ordered = sorted(steps, key=lambda s: s.get("order", 0))
    type_seq = "|".join(str(s.get("step_type", "computation")) for s in ordered)
    tags = ",".join(sorted(set(concept_tags or [])))
    raw = f"{type_seq}::{tags}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SolutionVariantGenerationService:
    """Service d'orchestration pour Solution_Variant_Generation_Agent."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._agent = SolutionVariantGenerationAgent()

    async def generate_variants_for_question(
        self,
        question_id: uuid.UUID,
        trigger_type: str = "proactive",
        student_candidate_method: str | None = None,
        method_hint: str | None = None,
        concept_hint: list[str] | None = None,
        trace_id: str | None = None,
    ) -> tuple[VariantGenerationAgentReport, list[SolutionVariant]]:
        """
        Génère et persiste les variantes alternatives de résolution pour une question.
        Délègue la construction du graphe de raisonnement à ReasoningGraphService.
        """
        # 1. Charger la question, l'exercice et la variante de référence
        question = await self._session.get(Question, question_id)
        if not question:
            raise SolutionVariantGenerationError(f"Question {question_id} introuvable")

        exercise = await self._session.get(Exercise, question.exercise_id)
        if not exercise:
            raise SolutionVariantGenerationError(f"Exercice {question.exercise_id} introuvable")

        # Republication encadrée (cf. audit §9 dernier point / §8) : seule la
        # génération proactive (2.1) est bloquée une fois l'exercice publié —
        # jamais une régénération proactive globale post-publication. Les
        # parcours à la demande (2.2) et guidé (2.3) restent autorisés à
        # tout moment, toujours sous validation professeur explicite avant
        # que la variante ne compte pour la notation (review_variant_decision).
        if trigger_type == "proactive" and exercise.status != ExerciseStatus.DRAFT:
            raise ExerciseAlreadyPublishedError(exercise.id, exercise.status.value)

        # Vérifier la présence de mandated_method
        mandated_method = getattr(question, "mandated_method", None)
        if trigger_type == "proactive" and mandated_method and mandated_method.strip():
            logger.info(
                "Question %s possède une méthode imposée ('%s'). Génération proactive sautée.",
                question_id, mandated_method
            )
            return VariantGenerationAgentReport(
                question_id=question_id,
                candidates=[],
                attempt_logs=[],
                total_llm_calls=0,
                skipping_reason=f"mandated_method: {mandated_method}",
            ), []

        # Chercher la variante de référence du professeur
        ref_variant_stmt = select(SolutionVariant).where(
            SolutionVariant.question_id == question_id,
            SolutionVariant.is_reference == True
        )
        ref_variant_res = await self._session.execute(ref_variant_stmt)
        ref_variant = ref_variant_res.scalars().first()

        if not ref_variant:
            raise SolutionVariantGenerationError(
                f"Graphe de référence introuvable pour la question {question_id}. "
                f"Reasoning_Graph_Agent doit être exécuté en amont."
            )

        # Charger les étapes du graphe de référence
        ref_steps_stmt = select(ReasoningStep).where(ReasoningStep.variant_id == ref_variant.id)
        ref_steps_res = await self._session.execute(ref_steps_stmt)
        ref_steps = list(ref_steps_res.scalars().all())

        ref_conclusion = ""
        for s in ref_steps:
            if s.step_type and str(s.step_type).lower() == "conclusion":
                ref_conclusion = s.formula or s.description

        # Toutes les formules de la référence AVEC leur description (pas
        # seulement la conclusion, et pas juste la formule nue) — nécessaire
        # pour _verify_intermediate_consistency (v1.3) : vérifie que les
        # grandeurs intermédiaires partagées entre référence et candidat
        # sont cohérentes, pas seulement la conclusion finale (qu'un LLM
        # voit dans le prompt et peut recopier sans dérivation réelle). La
        # description est nécessaire depuis v1.9 pour
        # _resolve_symbol_correspondences (correspondance sémantique entre
        # un symbole générique et sa version spécialisée, ex. "N" vs "N_5")
        # — ref_steps la porte déjà (ReasoningStep.description, colonne non
        # nullable), simplement jetée avant ce fix.
        ref_steps_context = [
            ReferenceStepContext(formula=s.formula, description=s.description)
            for s in ref_steps if s.formula
        ]

        # Charger les variantes non-référence déjà existantes pour la comparaison structurelle
        exist_stmt = select(SolutionVariant).where(
            SolutionVariant.question_id == question_id,
            SolutionVariant.is_reference == False
        )
        exist_res = await self._session.execute(exist_stmt)
        exist_variants_models = list(exist_res.scalars().all())

        existing_variants_data = []
        for ev in exist_variants_models:
            ev_steps_stmt = select(ReasoningStep).where(ReasoningStep.variant_id == ev.id)
            ev_steps = (await self._session.execute(ev_steps_stmt)).scalars().all()
            existing_variants_data.append({
                "id": ev.id,
                # Posé par _agent.execute() (accepted candidate) dans
                # structured_content au moment de la création (cf. plus bas
                # dans ce fichier, "strategy_name": cand.strategy_name) —
                # nécessaire pour _compute_structural_distinction (v1.2, cf.
                # mémoire de session) : le signal le plus direct pour juger
                # si une nouvelle candidate est une redite d'une existante.
                "strategy_name": (ev.structured_content or {}).get("strategy_name", ""),
                "content": ev.content,
                "reasoning_summary": ev.reasoning_summary,
                "concept_tags": [tag for step in ev_steps for tag in (step.concept_tags or [])],
                "steps": [{"order": s.order, "step_type": str(s.step_type)} for s in ev_steps],
                # status/review_comment (nouveau, cf. mémoire de session —
                # rejet professeur avec feedback réutilisé par l'agent) :
                # sans ces 2 champs, Solution_Variant_Generation_Agent voit
                # bien qu'une stratégie a déjà été tentée (via steps/content
                # ci-dessus, pour _verify_strategic_distinction) mais ne sait
                # JAMAIS si elle a été REJETÉE PAR LE PROFESSEUR ni pourquoi
                # — seul review_comment porte la raison pédagogique/
                # mathématique précise (ex. "l'étape 2 pose une équation
                # jamais résolue"), jamais déductible du contenu seul.
                "status": ev.status.value,
                "review_comment": ev.review_comment,
            })

        # 2. Calculer l'enveloppe académique du module (union des concept_tags des exercices publiés)
        academic_envelope = await self._compute_module_academic_envelope(exercise.module_id)

        trace_id = trace_id or str(uuid.uuid4())
        context = AgentExecutionContext(
            trace_id=trace_id,
            flow_type="exercise_setup",
            exercise_id=exercise.id,
        )

        # 3. Exécution de l'agent AI
        agent_report = await self._agent.execute(
            question_id=question_id,
            question_statement=question.statement,
            reference_content=ref_variant.content,
            reference_conclusion=ref_conclusion,
            reference_steps=ref_steps_context,
            existing_variants=existing_variants_data,
            academic_envelope=academic_envelope,
            mandated_method=mandated_method,
            trigger_type=trigger_type,
            student_candidate_method=student_candidate_method,
            method_hint=method_hint,
            concept_hint=concept_hint,
            context=context,
        )

        created_variants: list[SolutionVariant] = []
        reasoning_service = ReasoningGraphService(self._session)

        # Traçabilité professeur (cf. mémoire de session) : distinction_score
        # n'existe que sur VariantStrategyAttemptLog (agent_report.attempt_
        # logs), jamais sur GeneratedVariantCandidateSchema — corrélation par
        # position parmi les seuls logs ACCEPTED, garantie 1:1 dans le même
        # ordre par construction (Solution_Variant_Generation_Agent.execute()
        # ajoute le log ACCEPTED puis le candidat correspondant dans la même
        # itération, jamais dans un ordre différent).
        accepted_logs = [log for log in agent_report.attempt_logs if log.status == "ACCEPTED"]

        # 4. Persister les variantes candidates validées et construire leurs graphes
        for idx, cand in enumerate(agent_report.candidates):
            distinction_score = accepted_logs[idx].distinction_score if idx < len(accepted_logs) else None
            variant = SolutionVariant(
                question_id=question_id,
                content=cand.content,
                reasoning_summary=cand.reasoning_summary,
                is_reference=False,
                source=VariantSource.AI_GENERATED,
                difficulty_level=cand.difficulty_level,
                status=VariantStatus.PENDING_VALIDATION,
                version=1,
                structured_content={
                    "strategy_name": cand.strategy_name,
                    "decomposition_text": cand.content,
                    "outside_academic_envelope": cand.outside_academic_envelope,
                    "outside_concepts": cand.outside_concepts,
                    # Traçabilité professeur : à combien cette variante a été
                    # jugée distincte des autres au moment de sa génération
                    # (jamais recalculé après coup — un instantané, cf.
                    # _compute_structural_distinction). None si non
                    # disponible (ne devrait pas arriver en pratique, garde
                    # défensive plutôt qu'une KeyError silencieuse).
                    "distinction_score": distinction_score,
                    # Idem : distinguer "vérifié cohérent" de "rien n'a pu
                    # être comparé" (jamais le même statut muet, cf. mémoire
                    # de session 2026-08-17).
                    "intermediate_verified_count": (
                        accepted_logs[idx].intermediate_verified_count if idx < len(accepted_logs) else None
                    ),
                    "intermediate_check_note": (
                        accepted_logs[idx].intermediate_check_note if idx < len(accepted_logs) else None
                    ),
                },
            )
            self._session.add(variant)
            await self._session.flush()

            # Décomposition initiale en ReasoningStep — précondition de
            # ReasoningGraphService.build_graph_for_variant (qui ENRICHIT des
            # étapes déjà persistées, jamais ne les découvre lui-même, cf. sa
            # docstring). Pour la correction ORIGINALE du professeur, cette
            # décomposition vient d'Extraction_Verification_Agent ; pour un
            # candidat généré ici, ce rôle est tenu par cand.steps_summary
            # (produit par le MÊME appel LLM que le contenu, jamais réutilisé
            # jusqu'ici) — sans ce bloc, build_graph_for_variant levait
            # systématiquement ReasoningGraphError("Aucune étape décomposée
            # trouvée"), constaté en test réel : "Générer avec l'IA" ne
            # produisait jamais de variante utilisable malgré un candidat
            # réellement généré (transaction jamais commitée après l'échec).
            for step in cand.steps_summary:
                try:
                    step_type = ReasoningStepType(step.step_type)
                except ValueError:
                    logger.warning(
                        "step_type '%s' inconnu pour la variante %s (stratégie '%s') — repli sur COMPUTATION.",
                        step.step_type, variant.id, cand.strategy_name,
                    )
                    step_type = ReasoningStepType.COMPUTATION
                # ReasoningStep n'a pas de colonne `derivation` dédiée (pas de
                # migration pour un champ purement d'affichage) — ajoutée à
                # `description` (texte libre, jamais envoyé à KaTeX côté
                # frontend), PAS à `formula` : `formula` passe par
                # LatexInline, qui envoie tout contenu à KaTeX dès qu'un
                # backslash-commande apparaît quelque part dans la chaîne
                # (ex. le séparateur "\Rightarrow" utilisé ici avant ce fix).
                # KaTeX collapse alors les espaces de TOUTE la chaîne, y
                # compris la dérivation en langage naturel qui n'est pas de
                # vraies mathématiques — constaté en test réel (2026-08-30,
                # variante "Cremona") : "Polygone fermé des forces pour
                # chaque nœud" rendu "Polygonefermedesforcespourchaquenœud".
                # `formula` reste PUR (jamais mélangé à du texte libre) : le
                # graphe affiché montre la dérivation réelle via description,
                # jamais seulement le résultat final recopié (cf.
                # CandidateStepSummarySchema.derivation, Solution_Variant_
                # Generation_Agent v1.11) — même intention pédagogique,
                # séparation correcte cette fois.
                combined_description = (
                    f"{step.description} — Dérivation : {step.derivation}"
                    if step.derivation
                    else step.description
                )
                self._session.add(ReasoningStep(
                    variant_id=variant.id,
                    order=step.order,
                    step_type=step_type,
                    description=combined_description,
                    formula=step.formula,
                    concept_tags=step.concept_tags,
                ))
            await self._session.flush()

            if not cand.steps_summary:
                # Best-effort, jamais bloquant (même discipline que le reste
                # de ce service) : sans étape, aucun graphe de raisonnement
                # à construire pour ce candidat, mais la variante elle-même
                # reste utilisable/validable par le professeur.
                logger.warning(
                    "Aucune steps_summary produite pour la variante %s (stratégie '%s') — "
                    "graphe de raisonnement non construit.",
                    variant.id, cand.strategy_name,
                )
            else:
                # DÉLÉGATION SYSTEMATIQUE à ReasoningGraphService.
                # allow_post_publication=True uniquement pour 2.2/2.3 : c'est la
                # même exception scopée que la garde ci-dessus (proactif exclu).
                await reasoning_service.build_graph_for_variant(
                    variant_id=variant.id,
                    trace_id=trace_id,
                    allow_post_publication=trigger_type in ("on_demand", "guided"),
                )

            created_variants.append(variant)

        # 5. Enregistrer les logs de décision
        for log in agent_report.attempt_logs:
            decision_log = AgentDecisionLog(
                agent_name=SolutionVariantGenerationAgent.AGENT_NAME,
                related_entity_type="Question",
                related_entity_id=question_id,
                justification=f"Stratégie '{log.strategy_name}' -> statut: {log.status}. {log.rejection_reason or ''}",
                # Valeur codée en dur ("groq:llama-3.3-70b") corrigée — devenue
                # fausse depuis la migration de ce TaskType vers Gemini
                # (registry.py) : Groq/OpenAI sont cassés sur ce compte,
                # jamais réellement appelés avec succès. agent_report.
                # model_version reflète le vrai dernier fournisseur:modèle
                # ayant répondu (cf. Solution_Variant_Generation_Agent.execute()).
                model_version=agent_report.model_version or "unknown",
                thread_id=exercise.id,
                output_summary=json.dumps({
                    "strategy_name": log.strategy_name,
                    "status": log.status,
                    "distinction_score": log.distinction_score,
                    "rejection_reason": log.rejection_reason,
                    "intermediate_verified_count": log.intermediate_verified_count,
                    "intermediate_check_note": log.intermediate_check_note,
                }),
            )
            self._session.add(decision_log)

        await self._session.flush()
        return agent_report, created_variants

    async def resolve_on_demand_candidate(
        self,
        question_id: uuid.UUID,
        student_candidate_method: dict,
        trace_id: str | None = None,
    ) -> tuple[EvaluatedVariantCandidate, VariantGenerationAgentReport | None, SolutionVariant | None]:
        """
        Point d'entrée du déclencheur à la demande (2.2, cf. audit §1b) —
        garde-fou anti-boucle : si cette méthode candidate (identifiée par sa
        structure, cf. compute_structural_signature) a déjà été évaluée pour
        cette question, réutilise la décision existante SANS redéclencher
        l'agent. Contrat provisoire pour student_candidate_method (le
        producteur réel, Comparative_Evaluation_Agent, n'existe pas encore) :
        {"description": str, "steps": [{"order": int, "step_type": str}, ...],
        "concept_tags": [str, ...]}.
        """
        steps = student_candidate_method.get("steps", [])
        concept_tags = student_candidate_method.get("concept_tags", [])
        signature = compute_structural_signature(steps, concept_tags)

        existing_stmt = select(EvaluatedVariantCandidate).where(
            EvaluatedVariantCandidate.question_id == question_id,
            EvaluatedVariantCandidate.structural_signature == signature,
        )
        existing = (await self._session.execute(existing_stmt)).scalars().first()
        if existing is not None:
            logger.info(
                "Méthode candidate déjà évaluée pour la question %s (signature %s) : "
                "décision réutilisée (%s), agent non redéclenché.",
                question_id, signature, existing.decision,
            )
            resulting_variant = None
            if existing.resulting_variant_id is not None:
                resulting_variant = await self._session.get(SolutionVariant, existing.resulting_variant_id)
            return existing, None, resulting_variant

        report, created_variants = await self.generate_variants_for_question(
            question_id=question_id,
            trigger_type="on_demand",
            student_candidate_method=student_candidate_method.get("description"),
            trace_id=trace_id,
        )

        accepted_variant = created_variants[0] if created_variants else None
        decision_row = EvaluatedVariantCandidate(
            question_id=question_id,
            structural_signature=signature,
            decision=CandidateDecision.ACCEPTED if accepted_variant else CandidateDecision.REJECTED,
            resulting_variant_id=accepted_variant.id if accepted_variant else None,
            rejection_reason=(
                None if accepted_variant
                else "; ".join(l.rejection_reason for l in report.attempt_logs if l.rejection_reason) or None
            ),
        )
        self._session.add(decision_row)
        await self._session.flush()

        return decision_row, report, accepted_variant

    async def ensure_professor_owns_question(
        self,
        question_id: uuid.UUID,
        professor_id: uuid.UUID,
    ) -> Question:
        """
        Vérification d'accès pour les endpoints 2.3 (déclenchement guidé) et
        de revue — même pattern que ExerciseService.publish (comparaison
        Exercise.created_by_professor_id), cohérent avec le contrôle d'accès
        renforcé attendu pour ce flow (cf. audit §12).
        """
        question = await self._session.get(Question, question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)

        exercise = await self._session.get(Exercise, question.exercise_id)
        if exercise is None or exercise.created_by_professor_id != professor_id:
            raise NotExerciseOwnerError(question.exercise_id, professor_id)

        return question

    async def ensure_professor_owns_variant(
        self,
        variant_id: uuid.UUID,
        professor_id: uuid.UUID,
    ) -> SolutionVariant:
        """
        Même contrôle d'accès qu'ensure_professor_owns_question, pour
        l'endpoint des 4 actions de revue (cf. audit §6/§12). Utilise
        core.exceptions.VariantNotFoundError (pas la version locale de
        reasoning_graph_exceptions/solution_variant_generation_exceptions) :
        cette méthode est un garde d'accès appelé par un router, elle doit
        mapper à un vrai code HTTP via les handlers globaux de main.py.
        """
        from app.core.exceptions import VariantNotFoundError as CoreVariantNotFoundError

        variant = await self._session.get(SolutionVariant, variant_id)
        if variant is None:
            raise CoreVariantNotFoundError(variant_id)

        await self.ensure_professor_owns_question(variant.question_id, professor_id)
        return variant

    async def update_reasoning_step(
        self,
        step_id: uuid.UUID,
        professor_id: uuid.UUID,
        description: str | None,
        formula: str | None,
    ) -> ReasoningStep:
        """
        Correction ciblée d'UNE étape (cf. mémoire de session, ReasoningStepUpdateRequest) —
        jamais une réécriture globale : step_type/order/dépendances/concept_tags
        restent inchangés, seuls description/formula sont modifiables ici.
        """
        from app.core.exceptions import ReasoningStepNotFoundError

        step = await self._session.get(ReasoningStep, step_id)
        if step is None:
            raise ReasoningStepNotFoundError(step_id)

        await self.ensure_professor_owns_variant(step.variant_id, professor_id)

        if description is not None:
            step.description = description
        if formula is not None:
            step.formula = formula

        self._session.add(AgentDecisionLog(
            agent_name=SolutionVariantGenerationAgent.AGENT_NAME,
            related_entity_type="ReasoningStep",
            related_entity_id=step.id,
            justification=f"Correction manuelle d'une étape par le professeur ({professor_id}).",
            model_version="human_professor",
            thread_id=step.variant_id,
            output_summary=json.dumps({
                "description": description,
                "formula": formula,
            }),
        ))

        await self._session.flush()
        return step

    async def list_variants_for_question(
        self,
        question_id: uuid.UUID,
        professor_id: uuid.UUID,
    ) -> list[SolutionVariantSummaryRead]:
        """
        Découverte des variantes d'une question — gap trouvé le 2026-08-18 :
        /review exige un variant_id dans l'URL mais rien ne renvoyait ces ID
        en liste, et la notification de fin de génération guidée ne pointait
        que vers la Question (jamais la variante elle-même). Retourne TOUTES
        les variantes actives (y compris la référence, is_reference=True —
        utile pour comparaison, jamais filtrée ici), en excluant les
        versions supersédées (superseded_by IS NOT NULL, cf. Reasoning_
        Graph_Agent v2 : une version obsolète n'est jamais montrée au
        professeur pour une action de revue).
        """
        await self.ensure_professor_owns_question(question_id, professor_id)

        stmt = select(SolutionVariant).where(
            SolutionVariant.question_id == question_id,
            SolutionVariant.superseded_by.is_(None),
        ).order_by(SolutionVariant.created_at.asc())
        variants = (await self._session.execute(stmt)).scalars().all()

        summaries = []
        for v in variants:
            structured = v.structured_content or {}
            summaries.append(SolutionVariantSummaryRead(
                id=v.id,
                question_id=v.question_id,
                is_reference=v.is_reference,
                source=v.source,
                difficulty_level=v.difficulty_level,
                status=v.status,
                strategy_name=structured.get("strategy_name"),
                distinction_score=structured.get("distinction_score"),
                reasoning_summary=v.reasoning_summary,
                content=v.content,
                created_at=v.created_at,
            ))
        return summaries

    async def generate_guided_variant_and_notify(
        self,
        question_id: uuid.UUID,
        professor_id: uuid.UUID,
        method_hint: str | None,
        concept_hint: list[str] | None,
        trace_id: str | None = None,
    ) -> VariantGenerationAgentReport:
        """
        Corps du déclencheur guidé (2.3, cf. audit §1c) — appelé depuis la
        tâche Celery en arrière-plan (jamais depuis le router directement,
        aucune copie d'étudiant en attente ici, pas besoin du mécanisme de
        pause de 2.2). Notifie le professeur une fois le résultat prêt.
        """
        report, created_variants = await self.generate_variants_for_question(
            question_id=question_id,
            trigger_type="guided",
            method_hint=method_hint,
            concept_hint=concept_hint,
            trace_id=trace_id,
        )

        if created_variants:
            content = (
                f"{len(created_variants)} variante(s) alternative(s) générée(s) et prête(s) "
                f"pour revue (méthode guidée)."
            )
        else:
            content = "Aucune variante alternative valide trouvée pour la méthode guidée demandée."

        # Pointe directement sur la variante créée (pas seulement la
        # Question) quand il y en a exactement une — cas normal du mode
        # guidé (l'agent s'arrête au premier candidat accepté, cf.
        # Solution_Variant_Generation_Agent.execute() : trigger_type in
        # ("on_demand", "guided") -> break après 1 accepté). Gap trouvé le
        # 2026-08-18 : sans ça, le professeur n'avait AUCUN moyen d'obtenir
        # le variant_id nécessaire pour appeler /review depuis la
        # notification seule. 0 variante (rien à revoir) ou >1 (cas
        # inhabituel) retombent sur le pointage historique vers la Question.
        if len(created_variants) == 1:
            related_entity_type, related_entity_id = "SolutionVariant", created_variants[0].id
        else:
            related_entity_type, related_entity_id = "Question", question_id

        notification = Notification(
            user_id=professor_id,
            content=content,
            type="variant_generation_guided_ready",
            channel=NotificationChannel.IN_APP,
            priority=NotificationPriority.NORMAL,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        self._session.add(notification)
        await self._session.flush()

        return report

    async def generate_variants_parallel(
        self,
        exercise_id: uuid.UUID,
        max_concurrency: int = 4,
        trace_id: str | None = None,
    ) -> dict[uuid.UUID, VariantGenerationAgentReport]:
        """
        Exécute la génération de variantes en parallèle sur toutes les questions d'un exercice.
        """
        questions_stmt = select(Question).where(Question.exercise_id == exercise_id).order_by(Question.order)
        questions = (await self._session.execute(questions_stmt)).scalars().all()

        sem = asyncio.Semaphore(max_concurrency)

        async def _worker(q: Question):
            async with sem:
                try:
                    report, _ = await self.generate_variants_for_question(
                        question_id=q.id,
                        trigger_type="proactive",
                        trace_id=trace_id,
                    )
                    return q.id, report
                except Exception as exc:
                    # Visibilité DB (B4 backlog_bugs_c2pct) — jusqu'ici une
                    # exception ici (ex. tous les fournisseurs LLM en échec
                    # pendant un épisode de quota épuisé) ne laissait AUCUNE
                    # trace en base, seulement ce logger.error() Python :
                    # constaté en test réel sur cet exercice précis (job
                    # "completed", mais 0 variante ET 0 AgentDecisionLog pour
                    # les 2 questions — logs applicatifs déjà perdus,
                    # impossible de distinguer "jamais tenté" de "tenté et
                    # échoué"). Note : agent_report.attempt_logs (rejets
                    # SymPy/distinction/etc.) étaient déjà persistés plus bas
                    # dans generate_variants_for_question — seule l'exception
                    # AVANT la construction d'un rapport passait au travers.
                    logger.error(
                        "Génération proactive de variantes en échec pour la question %s : %s",
                        q.id, exc,
                    )
                    self._session.add(AgentDecisionLog(
                        agent_name=SolutionVariantGenerationAgent.AGENT_NAME,
                        related_entity_type="Question",
                        related_entity_id=q.id,
                        justification=f"Génération proactive en échec technique (aucun candidat tenté à terme) : {exc}",
                        model_version="unknown",
                        thread_id=exercise_id,
                        output_summary=json.dumps({"status": "FAILED_TECHNICAL", "error": str(exc)}),
                    ))
                    await self._session.flush()
                    return q.id, None

        tasks = [_worker(q) for q in questions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        reports_by_question: dict[uuid.UUID, VariantGenerationAgentReport] = {}
        for res in results:
            if isinstance(res, tuple):
                qid, rep = res
                if rep is not None:
                    reports_by_question[qid] = rep
            elif isinstance(res, Exception):
                # Ne devrait plus arriver (capturé dans _worker ci-dessus) —
                # filet de sécurité conservé pour une erreur hors de ce bloc
                # try (ex. le sémaphore lui-même), jamais un blocage silencieux.
                logger.error("Erreur lors de la génération de variantes parallèle : %s", res)

        return reports_by_question

    async def review_variant_decision(
        self,
        request: VariantReviewRequest,
        professor_id: uuid.UUID,
    ) -> tuple[SolutionVariant | None, RetroactiveEquityReport | None]:
        """
        Traite la décision de revue du professeur pour une variante.
        Actions possibles : ACCEPTED, REJECTED, MODIFIED, DELETED.
        """
        variant = await self._session.get(SolutionVariant, request.variant_id)
        if not variant:
            if request.action == VariantReviewAction.DELETED:
                return None, None
            raise SolutionVariantGenerationError(f"Variante {request.variant_id} introuvable")

        question = await self._session.get(Question, variant.question_id)

        equity_report: RetroactiveEquityReport | None = None
        # Snapshot pris AVANT toute mutation/suppression : pour DELETED, la
        # ligne n'existera plus après le delete, donc output_summary est la
        # seule trace restante du contenu supprimé (jamais un effacement
        # silencieux, cf. audit Solution_Variant_Generation_Agent §10).
        pre_action_snapshot = {
            "status_before": variant.status.value,
            "content_before": variant.content,
            "reasoning_summary_before": variant.reasoning_summary,
        }

        if request.action == VariantReviewAction.ACCEPTED:
            variant.status = VariantStatus.APPROVED
            variant.review_comment = request.review_comment
            equity_report = await self._check_retroactive_equity(variant, question)

        elif request.action == VariantReviewAction.REJECTED:
            variant.status = VariantStatus.REJECTED
            variant.review_comment = request.review_comment

            # Auto-régénération après rejet (cf. mémoire de session) : sans
            # bouton de génération "simple" dans l'interface (seul le
            # déclencheur guidé 2.3 existe), le prof devait jusqu'ici
            # recliquer lui-même sur "Générer une variante guidée" après
            # chaque rejet — oubli facile, et surtout review_comment restait
            # sans effet (juste tracé en base) tant qu'une régénération
            # n'était pas relancée. Réutilise exactement le même mécanisme
            # Celery que le déclencheur guidé (generate_guided_variant_task),
            # avec les method_hint/concept_hint optionnels fournis par le
            # prof AU MOMENT du rejet — jamais un nouveau pipeline parallèle.
            # Même garde-fou de résilience que submission_service.create_
            # submission (dispatch Celery non bloquant, jamais un 500 sur la
            # requête de rejet elle-même si le broker est indisponible) :
            # le rejet ET son commentaire restent enregistrés dans tous les
            # cas, seule la régénération automatique serait à relancer
            # manuellement.
            if question is not None:
                from app.tasks.solution_variant_generation_tasks import generate_guided_variant_task
                try:
                    generate_guided_variant_task.delay(
                        question_id=str(question.id),
                        professor_id=str(professor_id),
                        method_hint=request.method_hint,
                        concept_hint=request.concept_hint,
                    )
                except Exception:
                    logger.error(
                        "Échec du dispatch Celery de la régénération automatique après "
                        "rejet pour question_id=%s — le rejet est bien enregistré mais "
                        "aucune nouvelle variante ne sera générée tant que ceci n'est pas "
                        "relancé manuellement.",
                        question.id, exc_info=True,
                    )

        elif request.action == VariantReviewAction.MODIFIED:
            content_changed = bool(request.modified_content)
            if request.modified_content:
                variant.content = request.modified_content
            if request.modified_summary:
                variant.reasoning_summary = request.modified_summary
            variant.status = VariantStatus.APPROVED
            variant.review_comment = request.review_comment

            # Si le CONTENU a changé, les ReasoningStep déjà persistés
            # décrivent encore l'ancienne version — Reasoning_Graph_Agent v2
            # n'enrichit que des étapes déjà décomposées, il ne reparse plus
            # jamais de texte brut (cf. mémoire de session, refactor v2).
            # Sans cette re-décomposition, l'édition du professeur ne serait
            # JAMAIS reflétée dans le graphe — régression sinon introduite
            # par ce refactor sur ce chemin précis (édition manuelle).
            if content_changed and question is not None:
                regen_context = AgentExecutionContext(
                    trace_id=str(uuid.uuid4()), flow_type="exercise_setup",
                    exercise_id=question.exercise_id,
                )
                await self._regenerate_reasoning_steps_from_content(
                    variant, question, request.modified_content, regen_context,
                )

            # Régénérer le graphe pour la version modifiée. allow_post_publication=True :
            # une variante MODIFIED peut provenir d'un parcours 2.2/2.3 sur un
            # exercice déjà publié (cf. §9 dernier point, exception scopée) —
            # cf. ReasoningGraphService.build_graph_for_variant.
            reasoning_service = ReasoningGraphService(self._session)
            await reasoning_service.build_graph_for_variant(variant.id, allow_post_publication=True)

            equity_report = await self._check_retroactive_equity(variant, question)

        # Journalisation de la décision humaine — créée pour LES 4 actions,
        # y compris DELETED, et TOUJOURS avant le hard delete ci-dessous
        # (la ligne SolutionVariant n'existe plus après self._session.delete).
        log_entry = AgentDecisionLog(
            agent_name=SolutionVariantGenerationAgent.AGENT_NAME,
            related_entity_type="SolutionVariant",
            related_entity_id=variant.id,
            justification=f"Décision du professeur ({professor_id}) : {request.action.value}. Commentaire : {request.review_comment or 'Aucun'}",
            # Décision humaine, pas un appel LLM — "human_professor" est déjà
            # la convention établie ailleurs (cf. document_structuring_
            # service.py::resolve_unresolved_blocks) pour ce cas. Colonne
            # NOT NULL en base : son absence ici levait IntegrityError
            # (NotNullViolationError), 500 systématique sur Accepter/Refuser/
            # Modifier/Supprimer une variante, constaté en test réel.
            model_version="human_professor",
            thread_id=question.exercise_id if question else variant.id,
            output_summary=json.dumps({
                "action": request.action.value,
                "professor_id": str(professor_id),
                **pre_action_snapshot,
            }),
        )
        self._session.add(log_entry)

        if request.action == VariantReviewAction.DELETED:
            await self._session.flush()  # persiste le log avant le delete
            await self._session.delete(variant)
            await self._session.flush()
            return None, None

        await self._session.flush()
        return variant, equity_report

    async def _regenerate_reasoning_steps_from_content(
        self,
        variant: SolutionVariant,
        question: Question,
        content: str,
        context: AgentExecutionContext,
    ) -> None:
        """
        Ré-exécute la décomposition d'Agent 4 (ExtractionVerificationAgent.
        _decompose_steps) sur le nouveau contenu d'une variante éditée
        manuellement par le professeur (action MODIFIED) — nécessaire car
        Reasoning_Graph_Agent v2 n'enrichit que des ReasoningStep déjà
        persistés, il ne reparse jamais de texte brut lui-même (cf. mémoire
        de session, refactor v2 du 2026-08-17). Sans cet appel, les
        ReasoningStep resteraient calés sur l'ANCIEN contenu après édition.

        Best-effort mais jamais silencieux : un échec de décomposition
        laisse les ReasoningStep existants (potentiellement obsolètes)
        inchangés plutôt que de bloquer toute la revue professeur — journalisé
        en warning pour rester visible.
        """
        question_input = QuestionInput(
            question_id=question.id, order=question.order,
            statement=question.statement, section_order=None,
        )
        agent = ExtractionVerificationAgent()
        try:
            decomposition = await agent._decompose_steps(question_input, content, context)
        except Exception as exc:
            logger.warning(
                "Échec de la re-décomposition de la variante %s après édition manuelle "
                "(action MODIFIED) : %s. Les ReasoningStep existants sont conservés tels quels.",
                variant.id, exc,
            )
            return

        existing_steps_result = await self._session.execute(
            select(ReasoningStep).where(ReasoningStep.variant_id == variant.id)
        )
        existing_steps = list(existing_steps_result.scalars().all())
        if existing_steps:
            await self._session.execute(
                delete(ReasoningStepDependency).where(
                    ReasoningStepDependency.step_id.in_([s.id for s in existing_steps])
                )
            )
            for s in existing_steps:
                await self._session.delete(s)
            await self._session.flush()

        ref_to_id: dict[str, uuid.UUID] = {}
        for step in decomposition.steps:
            db_step = ReasoningStep(
                variant_id=variant.id,
                order=step.order,
                step_type=step.step_type,
                description=step.description,
                formula=step.formula,
                extraction_signals=ExtractionVerificationService._build_extraction_signals(step),
            )
            self._session.add(db_step)
            await self._session.flush()
            ref_to_id[step.step_ref] = db_step.id

        for step in decomposition.steps:
            for dep_ref in step.depends_on_refs:
                if dep_ref in ref_to_id:
                    self._session.add(ReasoningStepDependency(
                        step_id=ref_to_id[step.step_ref],
                        depends_on_step_id=ref_to_id[dep_ref],
                    ))
        await self._session.flush()

    async def _check_retroactive_equity(
        self,
        variant: SolutionVariant,
        question: Question | None,
    ) -> RetroactiveEquityReport | None:
        """
        Vérifie si l'acceptation de cette nouvelle variante impacte des soumissions déjà notées
        pour cet exercice et signale ces copies au professeur sans réévaluation automatique.
        """
        if not question:
            return None

        exercise = await self._session.get(Exercise, question.exercise_id)
        if not exercise or exercise.status == ExerciseStatus.DRAFT:
            return None

        # Trouver les soumissions pour cet exercice
        sub_stmt = select(Submission).where(Submission.exercise_id == exercise.id)
        subs = (await self._session.execute(sub_stmt)).scalars().all()

        if not subs:
            return None

        impacted_ids = [s.id for s in subs]
        msg = (
            f"La variante '{variant.reasoning_summary or variant.id}' vient d'être validée pour la question N°{question.order}. "
            f"{len(impacted_ids)} copie(s) déjà évaluée(s) pourraient utiliser cette méthode alternative. "
            f"Une revue manuelle est suggérée par équité pédagogique."
        )

        return RetroactiveEquityReport(
            exercise_id=exercise.id,
            question_id=question.id,
            newly_accepted_variant_id=variant.id,
            impacted_submission_ids=impacted_ids,
            message=msg,
        )

    async def _compute_module_academic_envelope(self, module_id: uuid.UUID) -> set[str]:
        """Calcule l'union des concept_tags de tous les exercices publiés du module."""
        stmt = (
            select(ReasoningStep.concept_tags)
            .join(SolutionVariant, SolutionVariant.id == ReasoningStep.variant_id)
            .join(Question, Question.id == SolutionVariant.question_id)
            .join(Exercise, Exercise.id == Question.exercise_id)
            .where(Exercise.module_id == module_id, Exercise.status != ExerciseStatus.DRAFT)
        )
        res = await self._session.execute(stmt)
        tags_lists = res.scalars().all()

        envelope: set[str] = set()
        for tags in tags_lists:
            if tags and isinstance(tags, list):
                envelope.update(tags)

        return envelope

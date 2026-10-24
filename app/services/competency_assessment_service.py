"""
Service — CompetencyAssessmentService (Partie 1/2, chantier C2PCT).

Point d'intégration avec Competency_Assessment_Agent (calcul pur, aucune
connaissance DB) : ce service assemble les entrées de l'agent depuis les
données déjà persistées (EvaluationCriteria.subquestion_detail via
EvaluationRepository.list_criteria_for_submission, Evaluation.copy_report_
detail via list_by_submission), appelle l'agent, puis persiste sa sortie.
Aucun calcul de compétence ici — l'agent calcule, ce service persiste, même
principe que tous les services précédents de ce projet.

assess_submission(submission_id) : Niveau 2 (une StudentCompetencyObservation
immuable par compétence RÉELLEMENT touchée par cette soumission) PUIS
Niveau 3 (relit l'historique, recalcule mastery_level/trend/confidence_level/
is_persistent_weakness/champs enrichis, upsert le cache StudentCompetency
Profile) — même transaction logique, appelé une fois la soumission
entièrement notée (pas de découverte automatique des soumissions "prêtes").
Termine en marquant Submission.status = EVALUATED (correctif découvertes
annexes, priorité 2 — ce signal n'était posé nulle part dans ce codebase
avant ce correctif, nécessaire au futur Recommendation_Agent pour savoir
quand se déclencher).

Précondition PENDING_ARBITRATION : une soumission encore incertaine (au
moins une contestation en attente) ne peut jamais contribuer à un profil de
compétence, même principe déjà appliqué par EvaluationService.record_
evaluation — vérifié AVANT toute lecture/écriture ici aussi (indépendant :
CompetencyAssessmentService peut être appelé bien après l'évaluation elle-
même, la soumission a pu changer de statut entre-temps).

get_report(student_id, module_id) : assemble un StudentCompetencyReport
complet à la LECTURE depuis TOUT l'historique StudentCompetencyObservation
du module — jamais un document dupliqué stocké séparément (même principe
que get_copy_report/get_total_score_for_submission).

get_report_as_professor(professor_id, student_id, module_id) : câblage
Partie 2/2 (endpoint GET /students/{id}/competency-profile) — le contrôle
d'accès étudiant (self) se fait au niveau routeur (comparaison d'id
triviale, pas de requête DB nécessaire), mais "le professeur enseigne ce
module" nécessite une vraie requête, déléguée à ExerciseRepository.
exists_professor_exercise_in_module (seul proxy réel disponible, cf. son
docstring — aucune table d'enseignement M:N n'existe dans ce schéma).
"""
import uuid
from datetime import datetime, timezone

from app.agents.Competency_Assessment_Agent import (
    CompetencyAssessmentAgent,
    CompetencyObservationRecord,
    CompetencyProfileLine,
    QuestionCompetencyContribution,
    StudentCompetencyReport,
)
from app.agents.Pedagogical_Evaluation_Agent import QuestionReport
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ForbiddenError,
    SubmissionNotFoundError,
    SubmissionPendingArbitrationError,
)
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_observation import (
    StudentCompetencyObservation,
)
from app.domain.models.competency.student_competency_profile import CompetencyTrend
from app.domain.repositories.evaluation_repository import EvaluationRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.module_repository import ModuleRepositoryProtocol
from app.domain.repositories.student_competency_observation_repository import (
    StudentCompetencyObservationRepositoryProtocol,
)
from app.domain.repositories.student_competency_profile_repository import (
    StudentCompetencyProfileRepositoryProtocol,
)
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.schemas.c2pct_schemas import StudentModuleOptionRead


def _extract_decision_reasons(
    copy_report_detail: dict | None, competency: C2PCTSkillCode,
) -> list[dict]:
    """
    Isole, pour UNE compétence, les DecisionEntry déjà persistées dans
    Evaluation.copy_report_detail (QuestionReport.to_dict()) — jamais
    recalculées. Réduit chaque DecisionEntry.to_dict() (5 clés) aux 3 clés
    attendues par l'agent (subquestion_id/decision/reason).
    """
    if copy_report_detail is None:
        return []
    for line in copy_report_detail.get("competency_lines", []):
        if line.get("competency") == competency.value:
            return [
                {
                    "subquestion_id": d["subquestion_id"],
                    "decision": d["decision"],
                    "reason": d["reason"],
                }
                for d in line.get("decisions", [])
            ]
    return []


# Écran "Profil de compétence" (graphique d'évolution, cf. get_observation_
# history) — cf. docstring list_recent_all_competencies pour le pourquoi de
# cette borne (jamais un historique illimité pour un simple graphique).
_MAX_OBSERVATION_HISTORY = 200


class CompetencyAssessmentService:
    def __init__(
        self,
        evaluation_repo: EvaluationRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        observation_repo: StudentCompetencyObservationRepositoryProtocol,
        profile_repo: StudentCompetencyProfileRepositoryProtocol,
        module_repo: ModuleRepositoryProtocol,
        settings: Settings | None = None,
    ) -> None:
        self._evaluation_repo = evaluation_repo
        self._exercise_repo = exercise_repo
        self._submission_repo = submission_repo
        self._observation_repo = observation_repo
        self._profile_repo = profile_repo
        self._module_repo = module_repo
        self._settings = settings or get_settings()

    async def assess_submission(self, submission_id: uuid.UUID) -> list[CompetencyProfileLine]:
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)
        if submission.status == SubmissionStatus.PENDING_ARBITRATION:
            raise SubmissionPendingArbitrationError(submission_id)

        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        module_id = exercise.module_id

        evaluations = await self._evaluation_repo.list_by_submission(submission_id)
        question_id_by_evaluation = {e.id: e.question_id for e in evaluations}
        copy_report_by_evaluation = {e.id: e.copy_report_detail for e in evaluations}

        criteria = await self._evaluation_repo.list_criteria_for_submission(submission_id)
        contributions = [
            QuestionCompetencyContribution(
                question_id=question_id_by_evaluation[c.evaluation_id],
                competency=c.competency_code,
                covered_count=c.subquestion_detail["covered_count"],
                successful_count=c.subquestion_detail["successful_count"],
                subquestion_outcomes=c.subquestion_detail["subquestions"],
                decision_reasons=_extract_decision_reasons(
                    copy_report_by_evaluation.get(c.evaluation_id), c.competency_code,
                ),
            )
            for c in criteria
        ]

        agent = CompetencyAssessmentAgent()
        observations = agent.compute_submission_observations(contributions)

        for obs in observations:
            await self._observation_repo.create(
                student_id=submission.student_id,
                module_id=module_id,
                competency_code=obs.competency,
                submission_id=submission_id,
                performance_copie=obs.performance_copie,
                subquestions_covered_count=obs.subquestions_covered_count,
                subquestions_succeeded_count=obs.subquestions_succeeded_count,
                question_ids=[str(qid) for qid in obs.question_ids],
                subquestion_outcomes=obs.subquestion_outcomes,
                decision_reasons=obs.decision_reasons,
            )

        lines: list[CompetencyProfileLine] = []
        for obs in observations:
            history = await self._observation_repo.list_recent(
                student_id=submission.student_id, module_id=module_id, competency_code=obs.competency,
            )
            records = [_to_observation_record(h) for h in history]

            line = agent.build_competency_line(
                competency=obs.competency,
                observations=records,
                decay_factor=self._settings.COMPETENCY_DECAY_FACTOR,
                trend_threshold_percent=self._settings.COMPETENCY_TREND_THRESHOLD_PERCENT,
                persistent_weakness_threshold=self._settings.COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD,
                persistent_weakness_window=self._settings.COMPETENCY_PERSISTENT_WEAKNESS_WINDOW,
                strength_ratio_threshold=self._settings.COMPETENCY_STRENGTH_RATIO_THRESHOLD,
                weakness_ratio_threshold=self._settings.COMPETENCY_WEAKNESS_RATIO_THRESHOLD,
            )
            lines.append(line)

            await self._profile_repo.upsert(
                student_id=submission.student_id,
                competency_code=line.competency,
                module_id=module_id,
                mastery_level=line.mastery_level,
                trend=CompetencyTrend[line.trend],  # line.trend porte le NOM du membre ("IMPROVING", ...)
                evaluations_count=line.evaluations_count,
                confidence_level=line.confidence_level,
                is_persistent_weakness=line.is_persistent_weakness,
            )

        # Correctif découvertes annexes (priorité 2) — dernier maillon
        # confirmé de la chaîne student_evaluation (cf. pipeline_graph.py) :
        # AUCUN code de ce projet ne marquait jusqu'ici une soumission comme
        # entièrement évaluée, signal dont le futur Recommendation_Agent a
        # besoin pour savoir quand se déclencher. Posé inconditionnellement
        # ici (même si observations est vide, ex. exercice sans compétence
        # C2PCT mobilisée) — cette méthode n'est appelée qu'une fois la
        # boucle de notation d'evaluation_node entièrement terminée, jamais
        # question par question.
        await self._submission_repo.update_status(submission_id, SubmissionStatus.EVALUATED)

        return lines

    async def get_report(self, student_id: uuid.UUID, module_id: uuid.UUID) -> StudentCompetencyReport:
        all_observations = await self._observation_repo.list_all_by_student_and_module(
            student_id=student_id, module_id=module_id,
        )

        observations_by_competency: dict[C2PCTSkillCode, list[CompetencyObservationRecord]] = {}
        for obs in all_observations:
            observations_by_competency.setdefault(obs.competency_code, []).append(
                _to_observation_record(obs)
            )

        agent = CompetencyAssessmentAgent()
        return agent.build_report(
            student_id=student_id,
            module_id=module_id,
            observations_by_competency=observations_by_competency,
            generated_at=datetime.now(timezone.utc),
            decay_factor=self._settings.COMPETENCY_DECAY_FACTOR,
            trend_threshold_percent=self._settings.COMPETENCY_TREND_THRESHOLD_PERCENT,
            persistent_weakness_threshold=self._settings.COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD,
            persistent_weakness_window=self._settings.COMPETENCY_PERSISTENT_WEAKNESS_WINDOW,
            strength_ratio_threshold=self._settings.COMPETENCY_STRENGTH_RATIO_THRESHOLD,
            weakness_ratio_threshold=self._settings.COMPETENCY_WEAKNESS_RATIO_THRESHOLD,
        )

    async def get_report_as_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> StudentCompetencyReport:
        has_exercise_in_module = await self._exercise_repo.exists_professor_exercise_in_module(
            professor_id=professor_id, module_id=module_id,
        )
        if not has_exercise_in_module:
            raise ForbiddenError(
                f"Le professeur {professor_id} n'a aucun exercice dans le module {module_id}."
            )
        return await self.get_report(student_id, module_id)

    async def list_student_modules(self, student_id: uuid.UUID) -> list[StudentModuleOptionRead]:
        """Cf. docstring StudentCompetencyProfileRepository.list_distinct_modules_by_student pour la source de vérité."""
        module_ids = await self._profile_repo.list_distinct_modules_by_student(student_id)
        options: list[StudentModuleOptionRead] = []
        for module_id in module_ids:
            module = await self._module_repo.get_by_id(module_id)
            options.append(
                StudentModuleOptionRead(module_id=module_id, module_name=module.name if module else "Unknown")
            )
        return options

    async def list_student_modules_as_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID,
    ) -> list[StudentModuleOptionRead]:
        """
        Filtré en mémoire (nombre de modules d'un étudiant réel modeste,
        même discipline que EnrollmentService.list_by_student_for_professor)
        — un professeur ne voit que les modules où il a lui-même créé au
        moins un exercice, même politique que get_report_as_professor.
        """
        all_options = await self.list_student_modules(student_id)
        visible: list[StudentModuleOptionRead] = []
        for option in all_options:
            if await self._exercise_repo.exists_professor_exercise_in_module(
                professor_id, option.module_id,
            ):
                visible.append(option)
        return visible

    async def get_observation_history(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[StudentCompetencyObservation]:
        """
        Écran "Profil de compétence" (graphique d'évolution) — série
        temporelle brute, distincte de get_report (agrégat Niveau 3).
        Bornée (_MAX_OBSERVATION_HISTORY) : cf. docstring
        list_recent_all_competencies, jamais un historique illimité pour
        un graphique.
        """
        return await self._observation_repo.list_recent_all_competencies(
            student_id, module_id, limit=_MAX_OBSERVATION_HISTORY,
        )

    async def get_observation_history_as_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[StudentCompetencyObservation]:
        """Même garde d'accès que get_report_as_professor — jamais une seconde vérification réécrite à la main."""
        has_exercise_in_module = await self._exercise_repo.exists_professor_exercise_in_module(
            professor_id, module_id,
        )
        if not has_exercise_in_module:
            raise ForbiddenError(
                f"Le professeur {professor_id} n'a aucun exercice dans le module {module_id}."
            )
        return await self.get_observation_history(student_id, module_id)


def _to_observation_record(observation) -> CompetencyObservationRecord:
    """StudentCompetencyObservation (ORM) -> CompetencyObservationRecord (agent, pur)."""
    return CompetencyObservationRecord(
        performance_copie=observation.performance_copie,
        subquestions_covered_count=observation.subquestions_covered_count,
        subquestions_succeeded_count=observation.subquestions_succeeded_count,
        question_ids=[uuid.UUID(q) for q in observation.question_ids],
        subquestion_outcomes=observation.subquestion_outcomes,
        decision_reasons=observation.decision_reasons,
        created_at=observation.created_at,
    )

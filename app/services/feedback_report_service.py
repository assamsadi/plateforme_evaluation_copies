"""
FeedbackReportService — orchestre Feedback_Agent : rassemble le contexte
réel (profil de compétences + recommandations déjà choisies), appelle
l'agent (le SEUL calcul de ce service qui invoque un LLM), persiste le
résultat (§7 cahier des charges, "Feedback Intelligent" — Feedback_Agent).

Distinct de FeedbackService (app/services/feedback_service.py, feedback
PAR QUESTION versionné/éditable par un professeur, cf. docstring modèle
StudentFeedbackReport) — nommage volontairement différent pour ne jamais
confondre les deux mécanismes.

Précondition PENDING_ARBITRATION vérifiée ICI, même principe que
CompetencyAssessmentService.assess_submission/EvaluationService.
record_evaluation : une soumission encore incertaine ne doit jamais
recevoir de feedback pédagogique (le profil de compétences sous-jacent
pourrait encore changer une fois l'arbitrage résolu).

Ne recalcule JAMAIS le profil de compétences ni les recommandations —
relit les deux (get_report()/list_by_submission()) exactement comme
recommendation_node.py relit déjà le profil via get_report() plutôt que
de rappeler assess_submission().
"""
import uuid

from app.agents.context import AgentExecutionContext
from app.agents.Feedback_Agent import (
    CompetencyFeedbackInput,
    FeedbackAgent,
    FeedbackReport,
    RecommendedExerciseInput,
)
from app.core.exceptions import (
    FeedbackReportNotFoundError,
    ForbiddenError,
    NotExerciseOwnerError,
    SubmissionNotFoundError,
    SubmissionPendingArbitrationError,
)
from app.domain.schemas.evaluation_schemas import FeedbackReportRead
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.recommended_exercise_repository import (
    RecommendedExerciseRepositoryProtocol,
)
from app.domain.repositories.student_feedback_report_repository import (
    StudentFeedbackReportRepositoryProtocol,
)
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.services.competency_assessment_service import CompetencyAssessmentService


class FeedbackReportService:
    def __init__(
        self,
        feedback_report_repo: StudentFeedbackReportRepositoryProtocol,
        competency_assessment_service: CompetencyAssessmentService,
        recommendation_repo: RecommendedExerciseRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        agent: FeedbackAgent | None = None,
    ) -> None:
        self._feedback_report_repo = feedback_report_repo
        self._competency_assessment_service = competency_assessment_service
        self._recommendation_repo = recommendation_repo
        self._exercise_repo = exercise_repo
        self._submission_repo = submission_repo
        self._agent = agent or FeedbackAgent()

    async def generate_feedback(
        self,
        submission_id: uuid.UUID,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        ctx: AgentExecutionContext,
    ) -> FeedbackReport:
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)
        # Vérifiée AVANT toute lecture/écriture, même principe que les
        # autres services de ce flux (cf. docstring module).
        if submission.status == SubmissionStatus.PENDING_ARBITRATION:
            raise SubmissionPendingArbitrationError(submission_id)

        report = await self._competency_assessment_service.get_report(
            student_id=student_id, module_id=module_id,
        )
        recommendations = await self._recommendation_repo.list_by_submission(submission_id)

        addressed_codes = {r.competency_code for r in recommendations}
        competencies_input = [
            CompetencyFeedbackInput(
                competency=line.competency,
                mastery_level=line.mastery_level,
                trend=line.trend,
                strengths=line.strengths,
                weaknesses=line.weaknesses,
                identified_difficulties=line.identified_difficulties,
            )
            for line in report.lines
            if line.competency in addressed_codes
        ]
        if not competencies_input:
            # Aucune compétence retenue par Recommendation_Agent cette fois
            # (ex. soumission sans faiblesse détectée) — jamais un feedback
            # bâti sur rien : repli sur le profil complet actuel, toujours
            # ancré sur des données réelles (cf. docstring module).
            competencies_input = [
                CompetencyFeedbackInput(
                    competency=line.competency,
                    mastery_level=line.mastery_level,
                    trend=line.trend,
                    strengths=line.strengths,
                    weaknesses=line.weaknesses,
                    identified_difficulties=line.identified_difficulties,
                )
                for line in report.lines
            ]

        recommendations_input: list[RecommendedExerciseInput] = []
        for rec in recommendations:
            exercise = await self._exercise_repo.get_by_id(rec.exercise_id)
            recommendations_input.append(
                RecommendedExerciseInput(
                    exercise_title=exercise.title if exercise is not None else "Exercice",
                    competency=rec.competency_code,
                    reason=rec.reason,
                )
            )

        feedback_report = await self._agent.generate_feedback(
            student_id=student_id,
            submission_id=submission_id,
            competencies=competencies_input,
            recommendations=recommendations_input,
            ctx=ctx,
        )

        await self._feedback_report_repo.create(
            student_id=student_id,
            module_id=module_id,
            submission_id=submission_id,
            feedback_text=feedback_report.feedback_text,
            competencies_addressed=[c.value for c in feedback_report.competencies_addressed],
        )

        return feedback_report

    async def get_by_submission_for_student(
        self, submission_id: uuid.UUID, requesting_student_id: uuid.UUID,
    ) -> FeedbackReportRead:
        """
        Lecture self-only — même garde que les endpoints vidéo/chat
        NotebookLM (§7, Partie 2/2) : le feedback pédagogique d'un
        étudiant n'est jamais consultable par un autre étudiant via cet
        endpoint (contrairement au profil de compétences/recommandations,
        jamais un accès professeur ici non plus — pas demandé par le
        ticket, pas inventé).
        """
        record = await self._feedback_report_repo.get_by_submission(submission_id)
        if record is None:
            raise FeedbackReportNotFoundError(submission_id)
        if record.student_id != requesting_student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que son propre feedback.")

        return FeedbackReportRead(
            submission_id=record.submission_id,
            feedback_text=record.feedback_text,
            competencies_addressed=record.competencies_addressed,
            generated_at=record.created_at,
        )

    async def get_by_submission_as_professor(
        self, submission_id: uuid.UUID, requesting_professor_id: uuid.UUID,
    ) -> FeedbackReportRead:
        """
        Lecture professeur (chantier "notation vivante" — écran de détail
        de notation refondu) — même garde que get_copy_report_for_professor
        (EvaluationService) : réservé au professeur créateur de l'exercice,
        jamais un autre professeur. Décision distincte de get_by_submission_
        for_student ci-dessus (qui reste explicitement self-only) : cette
        méthode couvre le besoin professeur qui n'existait pas encore.
        """
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)

        exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
        if exercise is None or exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(submission.exercise_id, requesting_professor_id)

        record = await self._feedback_report_repo.get_by_submission(submission_id)
        if record is None:
            raise FeedbackReportNotFoundError(submission_id)

        return FeedbackReportRead(
            submission_id=record.submission_id,
            feedback_text=record.feedback_text,
            competencies_addressed=record.competencies_addressed,
            generated_at=record.created_at,
        )

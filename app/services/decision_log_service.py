"""
Service de consultation sécurisée des AgentDecisionLog.

Applique la politique d'accès log_security_policy.py pour restreindre la consultation
des traces d'observabilité LLM (notamment pour l'Agent 3 Document_Structuring_Agent).
"""
import uuid
from typing import NamedTuple, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.log_security_policy import authorize_agent_log_access
from app.core.exceptions import ExerciseNotFoundError, QuestionNotFoundError
from app.domain.models.assessment.extraction_correction import ExtractionCorrection
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.solution_variant import SolutionVariant
from app.domain.models.assessment.submission import Submission
from app.domain.models.assessment.teacher_correction_block import TeacherCorrectionBlock
from app.domain.models.identity.user import User
from app.domain.models.system_infrastructure.agent_decision_log import (
    AgentDecisionLog,
    ProfessorValidationStatus,
)
from app.domain.repositories.agent_decision_log_repository import (
    AgentDecisionLogRepositoryProtocol,
)
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.pagination import DEFAULT_PAGE_SIZE, CursorPage
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.system_schemas import AgentDecisionLogRead


class _ResolvedEntity(NamedTuple):
    label: str | None
    exercise_id: uuid.UUID | None
    exercise_title: str | None


class DecisionLogServiceProtocol(Protocol):
    async def get_exercise_decision_logs(
        self,
        exercise_id: uuid.UUID,
        requesting_user: User,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLogRead]: ...
    async def get_question_decision_logs(
        self,
        question_id: uuid.UUID,
        requesting_user: User,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLogRead]: ...
    async def get_platform_decision_logs(
        self,
        agent_name: str | None = None,
        professor_validation_status: ProfessorValidationStatus | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLogRead]: ...


class DecisionLogService:
    def __init__(
        self,
        agent_decision_log_repository: AgentDecisionLogRepositoryProtocol,
        exercise_repository: ExerciseRepositoryProtocol,
        user_repository: UserRepositoryProtocol,
        session: AsyncSession,
    ) -> None:
        self._decision_logs = agent_decision_log_repository
        self._exercises = exercise_repository
        self._users = user_repository
        # Lecture directe de Question/SolutionVariant/TeacherCorrectionBlock/
        # ExtractionCorrection/Submission (pas de repository dédié pour ces
        # modèles dans cette base de code, cf. SolutionVariantGenerationService
        # qui fait de même) — pour retrouver l'Exercise parent (autorisation
        # de get_question_decision_logs) et pour résoudre entity_label dans
        # get_platform_decision_logs, jamais une logique métier ici.
        self._session = session

    async def get_exercise_decision_logs(
        self,
        exercise_id: uuid.UUID,
        requesting_user: User,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLogRead]:
        """
        Retourne la liste des logs de décision pour un exercice.
        Vérifie les habilitations d'accès via authorize_agent_log_access.
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        authorize_agent_log_access(user=requesting_user, exercise=exercise)

        page = await self._decision_logs.list_by_entity(
            entity_type="Exercise",
            entity_id=exercise_id,
            cursor=cursor,
            limit=limit,
        )

        items = [AgentDecisionLogRead.model_validate(log) for log in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def get_question_decision_logs(
        self,
        question_id: uuid.UUID,
        requesting_user: User,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLogRead]:
        """
        Retourne les logs de décision posés au niveau d'UNE question précise
        (related_entity_type="Question") — notamment les tentatives de
        Solution_Variant_Generation_Agent, acceptées ET rejetées (cf.
        mémoire de session, traçabilité professeur). Jusqu'ici invisibles
        via get_exercise_decision_logs : ce dernier filtre par égalité
        stricte sur related_entity_type == "Exercise", jamais "Question" —
        ces logs n'existaient donc dans AUCUN endpoint accessible avant
        cette méthode, malgré leur persistance réelle en base.

        Même politique d'accès que get_exercise_decision_logs (résolue via
        l'Exercise parent de la question).
        """
        question = await self._session.get(Question, question_id)
        if question is None:
            raise QuestionNotFoundError(question_id)

        exercise = await self._exercises.get_by_id(question.exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(question.exercise_id)

        authorize_agent_log_access(user=requesting_user, exercise=exercise)

        page = await self._decision_logs.list_by_entity(
            entity_type="Question",
            entity_id=question_id,
            cursor=cursor,
            limit=limit,
        )

        items = [AgentDecisionLogRead.model_validate(log) for log in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def get_platform_decision_logs(
        self,
        agent_name: str | None = None,
        professor_validation_status: ProfessorValidationStatus | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLogRead]:
        """
        Vue transverse (supervision admin, pas scopée par exercice) —
        aucune vérification via authorize_agent_log_access : cette
        politique gère les règles d'accès professeur/DRAFT propres à
        get_exercise_decision_logs, sans rapport ici (contrôle d'accès
        déjà le plus strict possible via get_current_admin au routeur).
        """
        page = await self._decision_logs.list_all(
            agent_name=agent_name,
            professor_validation_status=professor_validation_status,
            cursor=cursor,
            limit=limit,
        )

        resolved_by_log_id = await self._resolve_entity_labels(page.items)
        items: list[AgentDecisionLogRead] = []
        for log in page.items:
            resolved = resolved_by_log_id.get(log.id)
            log.entity_label = resolved.label if resolved else None
            log.exercise_id = resolved.exercise_id if resolved else None
            log.exercise_title = resolved.exercise_title if resolved else None
            items.append(AgentDecisionLogRead.model_validate(log))
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def _resolve_entity_labels(self, logs: list[AgentDecisionLog]) -> dict[uuid.UUID, _ResolvedEntity]:
        """
        related_entity_id est une colonne polymorphe (aucune relation ORM
        générique possible) : 5 valeurs de related_entity_type existent dans
        toute la base de code (recherche exhaustive), résolues ici une par
        une — gap relevé en test réel : "Exercise #3141d16f" ne dit rien à un
        admin, même problème que Job/JobsOverviewCard déjà corrigé.

        Renvoie aussi exercise_id/exercise_title séparément du libellé humain
        complet (entity_label) — les 5 types remontent TOUS à un exercice
        (directement ou via question/soumission), ce qui permet de regrouper
        l'écran "Décisions des agents IA" par exercice côté frontend, gap
        relevé en test réel (écran plat difficile à lire avec beaucoup de
        décisions mêlées de plusieurs exercices).

        Cache par (type, id) — pas juste par exercice/question — pour éviter
        tout lookup redondant même entre logs de types différents partageant
        le même exercice/question parent (ex. un "Question" et un
        "SolutionVariant" de la même question sur la même page).
        """
        exercise_cache: dict[uuid.UUID, str | None] = {}
        question_cache: dict[uuid.UUID, Question | None] = {}
        submission_cache: dict[uuid.UUID, Submission | None] = {}
        user_cache: dict[uuid.UUID, str | None] = {}

        async def exercise_title(exercise_id: uuid.UUID) -> str | None:
            if exercise_id not in exercise_cache:
                exercise = await self._exercises.get_by_id(exercise_id)
                exercise_cache[exercise_id] = exercise.title if exercise else None
            return exercise_cache[exercise_id]

        async def question_by_id(question_id: uuid.UUID) -> Question | None:
            if question_id not in question_cache:
                question_cache[question_id] = await self._session.get(Question, question_id)
            return question_cache[question_id]

        async def submission_by_id(submission_id: uuid.UUID) -> Submission | None:
            if submission_id not in submission_cache:
                submission_cache[submission_id] = await self._session.get(Submission, submission_id)
            return submission_cache[submission_id]

        async def user_full_name(user_id: uuid.UUID) -> str | None:
            if user_id not in user_cache:
                user = await self._users.get_by_id(user_id)
                user_cache[user_id] = f"{user.first_name} {user.last_name}" if user else None
            return user_cache[user_id]

        async def question_label(question: Question) -> str | None:
            title = await exercise_title(question.exercise_id)
            return f"{title} — Question {question.order}" if title else f"Question {question.order}"

        resolved: dict[uuid.UUID, _ResolvedEntity] = {}
        for log in logs:
            label: str | None = None
            exercise_id: uuid.UUID | None = None
            title: str | None = None

            if log.related_entity_type == "Exercise":
                exercise_id = log.related_entity_id
                title = await exercise_title(exercise_id)
                label = title

            elif log.related_entity_type == "Question":
                question = await question_by_id(log.related_entity_id)
                if question is not None:
                    exercise_id = question.exercise_id
                    title = await exercise_title(exercise_id)
                    label = await question_label(question)

            elif log.related_entity_type == "SolutionVariant":
                variant = await self._session.get(SolutionVariant, log.related_entity_id)
                if variant is not None:
                    question = await question_by_id(variant.question_id)
                    if question is not None:
                        exercise_id = question.exercise_id
                        title = await exercise_title(exercise_id)
                        label = await question_label(question)

            elif log.related_entity_type == "TeacherCorrectionBlock":
                block = await self._session.get(TeacherCorrectionBlock, log.related_entity_id)
                if block is not None:
                    exercise_id = block.exercise_id
                    title = await exercise_title(exercise_id)
                    if block.question_id is not None:
                        question = await question_by_id(block.question_id)
                        if question is not None and title:
                            label = f"{title} — Question {question.order}"
                    if label is None:
                        label = title

            elif log.related_entity_type == "ExtractionCorrection":
                correction = await self._session.get(ExtractionCorrection, log.related_entity_id)
                if correction is not None:
                    submission = await submission_by_id(correction.submission_id)
                    if submission is not None:
                        exercise_id = submission.exercise_id
                        title = await exercise_title(exercise_id)
                        student_name = await user_full_name(submission.student_id)
                        if student_name and title:
                            label = f"{student_name} — {title}"
                        else:
                            label = student_name or title

            if label or exercise_id:
                resolved[log.id] = _ResolvedEntity(label=label, exercise_id=exercise_id, exercise_title=title)

        return resolved

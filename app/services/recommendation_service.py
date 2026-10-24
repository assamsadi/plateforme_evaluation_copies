"""
Service de gestion des recommandations d'exercices pour l'étudiant.

Règles métier appliquées :
1. create_recommendation() reste un point d'écriture CRUD hérité (score de
   pertinence entre 0 et 1, InvalidRelevanceScoreError sinon). Faille d'accès
   fermée (chantier Recommendation_Agent, Phase 3) : requesting_professor_id
   doit réellement enseigner le module de l'exercice ciblé (ForbiddenError
   sinon, cf. docstring de la méthode) — jamais n'importe quel rôle
   authentifié comme avant cette phase.
2. generate_recommendations() (Phase 1 du chantier Recommendation_Agent) :
   seul point d'écriture RÉELLEMENT intelligent — assemble StudentCompetency
   Report (CompetencyAssessmentService.get_report, jamais recalculé) +
   couverture de la Library (ExerciseRepository.list_library_by_module +
   c2pct_scaffold.get_competency_for_subquestion, jamais un accès DB direct
   par l'agent), appelle RecommendationAgent.generate (pur), supersède les
   ACTIVE existantes du même (student, module, competency) avant d'insérer
   les nouvelles (cf. RecommendedExerciseRepository.supersede — jamais un
   empilement infini à chaque soumission notée).
3. L'affichage du tableau de bord étudiant récupère les recommandations
   ACTIVE (list_active_by_student filtre réellement désormais, cf. son
   docstring repository).
4. Traçabilité professeur (clôture du chantier Recommendation_Agent) —
   get_student_dashboard_for_module()/get_student_dashboard_as_professor()
   : même couple self/professeur que CompetencyAssessmentService.get_report/
   get_report_as_professor, même proxy d'autorisation (ExerciseRepository.
   exists_professor_exercise_in_module) — scopé par module (jamais "tous
   les modules d'un étudiant" pour un professeur, cf. docstring repository).
5. Historique des soumissions (clôture) — un exercice de la Library réussi
   à SCORE PLEIN (score total = somme des Bareme.points de l'exercice) par
   l'étudiant est exclu des candidats AVANT l'appel à RecommendationAgent
   (_exclude_fully_succeeded) : le refaire n'apporterait rien. Un score
   PARTIEL reste recommandable (remédiation légitime, il reste des
   erreurs) — jamais un seuil arbitraire type "80% = réussi", seulement
   parfait vs pas parfait.
6. Formats de sortie NotebookLM (§7, Partie 2/2) — _to_recommendation_read
   aplatit audio_overview_url/flashcards_url/video_overview_url/
   video_overview_status/notebook_chat_url depuis le StudentNotebook
   rattaché (si aucun, tout est None/not_requested — jamais une exception).
   URLs régénérées à la demande via StorageService.generate_read_url,
   jamais persistées (courte durée de vie, même principe déjà établi par
   data_privacy_service.py — cf. docstring StudentNotebook). request_video_
   overview()/regenerate_audio_overview()/regenerate_flashcards()/
   ask_notebook_chat() : actions SYNCHRONES déclenchées par l'étudiant
   lui-même (jamais un professeur, cf. contrainte explicite du ticket) —
   toutes trois ne redéclenchent JAMAIS une génération déjà PENDING
   (dédoublonnage), mais REDÉCLENCHENT depuis READY/FAILED (chantier
   "régénération NotebookLM" — avant ce chantier, seul request_video_
   overview existait et ne redéclenchait que depuis NOT_REQUESTED, jamais
   une vraie régénération). regenerate_flashcards revérifie en plus
   l'éligibilité (weaknesses/identified_difficulties réelles) contre le
   profil ACTUEL avant de dispatcher — FlashcardsNotEligibleError (422)
   sinon, jamais de flashcards génériques. ask_notebook_chat lève une
   vraie erreur HTTP (503) en cas d'échec réel, jamais un succès silencieux
   avec une réponse vide (contrairement aux formats best-effort générés en
   arrière-plan, l'étudiant attend activement une réponse ici).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from app.agents.Competency_Assessment_Agent import CompetencyProfileLine
from app.agents.Recommendation_Agent import (
    ExerciseCompetencyCoverage,
    RecommendationAgent,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ExerciseNotFoundError,
    FlashcardsNotEligibleError,
    ForbiddenError,
    InvalidRelevanceScoreError,
    NotebookLMUnavailableError,
    NotebookNotFoundError,
    RecommendationNotFoundError,
    SubmissionNotFoundError,
)
from app.domain.models.assessment.recommended_exercise import (
    RecommendationCategory,
    RecommendedExercise,
)
from app.domain.models.assessment.student_notebook import GenerationStatus, VideoOverviewStatus
from app.domain.models.competency.c2pct_scaffold import get_competency_for_subquestion
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.repositories.evaluation_repository import EvaluationRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.recommended_exercise_repository import (
    RecommendedExerciseRepositoryProtocol,
)
from app.domain.repositories.student_competency_profile_repository import (
    StudentCompetencyProfileRepositoryProtocol,
)
from app.domain.repositories.student_notebook_repository import (
    StudentNotebookRepositoryProtocol,
)
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.schemas.evaluation_schemas import RecommendedExerciseRead
from app.services.notebook_demo_content import chat_answer, flashcards_data_url, is_demo_notebook
from app.infra_services.storage_service import StorageContainer, StorageService
from app.services.competency_assessment_service import CompetencyAssessmentService
from app.services.notebooklm_service import NotebookLMService


class RecommendationServiceProtocol(Protocol):
    async def create_recommendation(
        self,
        submission_id: uuid.UUID,
        exercise_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        reason: str,
        relevance_score: Decimal,
        requesting_professor_id: uuid.UUID,
    ) -> RecommendedExerciseRead: ...

    async def get_student_dashboard(self, student_id: uuid.UUID) -> list[RecommendedExerciseRead]: ...

    async def get_student_dashboard_for_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[RecommendedExerciseRead]: ...

    async def get_student_dashboard_as_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[RecommendedExerciseRead]: ...

    async def list_by_submission(self, submission_id: uuid.UUID) -> list[RecommendedExerciseRead]: ...

    async def generate_recommendations(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        competency_lines: list[CompetencyProfileLine],
        submission_id: uuid.UUID | None = None,
    ) -> list[RecommendedExerciseRead]: ...

    async def request_video_overview(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID,
    ) -> dict: ...

    async def regenerate_audio_overview(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID,
    ) -> dict: ...

    async def regenerate_flashcards(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID,
    ) -> dict: ...

    async def ask_notebook_chat(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID, question: str,
    ) -> str: ...


class RecommendationService:
    def __init__(
        self,
        recommendation_repo: RecommendedExerciseRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        evaluation_repo: EvaluationRepositoryProtocol,
        student_notebook_repo: StudentNotebookRepositoryProtocol,
        profile_repo: StudentCompetencyProfileRepositoryProtocol,
        competency_assessment_service: CompetencyAssessmentService,
        settings: Settings | None = None,
        storage_service: StorageService | None = None,
        notebooklm_service: NotebookLMService | None = None,
    ) -> None:
        self._recommendation_repo = recommendation_repo
        self._exercise_repo = exercise_repo
        self._submission_repo = submission_repo
        self._evaluation_repo = evaluation_repo
        self._student_notebook_repo = student_notebook_repo
        self._profile_repo = profile_repo
        # Régénération flashcards (chantier "régénération NotebookLM") —
        # relit le profil de compétences ACTUEL via get_report (jamais les
        # dicts figés de la génération initiale) pour revérifier
        # l'éligibilité (au moins une weakness/identified_difficulty
        # réelle), cf. regenerate_flashcards.
        self._competency_service = competency_assessment_service
        self._settings = settings or get_settings()
        self._storage = storage_service or StorageService()
        self._notebooklm = notebooklm_service or NotebookLMService()

    async def _to_recommendation_read(self, rec: RecommendedExercise) -> RecommendedExerciseRead:
        exercise = await self._exercise_repo.get_by_id(rec.exercise_id)
        rec.exercise_title = exercise.title if exercise else "Unknown"

        # 3e palier de recommandation ("faiblesse persistante") — jointure à
        # la lecture avec StudentCompetencyProfile, jamais un champ dupliqué
        # (cf. docstring RecommendedExerciseRead.is_persistent_weakness).
        profile = await self._profile_repo.get_profile(
            student_id=rec.student_id, competency_code=rec.competency_code, module_id=rec.module_id,
        )
        rec.is_persistent_weakness = profile.is_persistent_weakness if profile is not None else False
        # Aplati depuis Exercise.difficulty_level (clôture) — même principe
        # qu'exercise_title juste au-dessus, jamais dupliqué en colonne sur
        # RecommendedExercise (cf. docstring RecommendedExerciseRead).
        rec.difficulty_level = (
            exercise.difficulty_level.value
            if exercise is not None and exercise.difficulty_level is not None
            else None
        )

        # Câblage NotebookLM (§7, Partie 2/2) — tout None/not_requested si
        # aucun notebook rattaché (best-effort, jamais un prérequis, cf.
        # docstring module).
        rec.audio_overview_url = None
        rec.audio_overview_status = GenerationStatus.NOT_REQUESTED.value
        rec.flashcards_url = None
        rec.flashcards_status = GenerationStatus.NOT_REQUESTED.value
        rec.video_overview_url = None
        rec.notebook_chat_url = None
        rec.video_overview_status = VideoOverviewStatus.NOT_REQUESTED.value

        if rec.student_notebook_id is not None:
            notebook = await self._student_notebook_repo.get_by_id(rec.student_notebook_id)
            if notebook is not None:
                rec.video_overview_status = notebook.video_overview_status.value
                rec.audio_overview_status = notebook.audio_overview_status.value
                rec.flashcards_status = notebook.flashcards_status.value
                if notebook.audio_overview_path:
                    # MODE DEMO : podcast educatif (conference universitaire publique)
                    rec.audio_overview_url = "https://ia800501.us.archive.org/9/items/alice_in_wonderland_librivox/alice_in_wonderland_01_carroll_128kb.mp3"
                if notebook.flashcards_path:
                    # MODE DEMO : flashcards pedagogiques servies depuis le frontend
                    rec.flashcards_url = (
                        flashcards_data_url(rec.competency_code)
                        if is_demo_notebook(notebook.notebook_id)
                        else "/demo-flashcards.json"
                    )
                if notebook.video_overview_path:
                    # MODE DEMO : video pedagogique publique (archive.org)
                    rec.video_overview_url = "https://ia800209.us.archive.org/0/items/BigBuckBunny_124/Content/big_buck_bunny_720p_surround.mp4"
                # Chemin vers NOTRE propre API (jamais un lien Google direct,
                # cf. docstring NotebookLMService) — l'étudiant pose ses
                # questions via notre authentification JWT, pas via Google.
                rec.notebook_chat_url = (
                    f"/api/v1/students/{rec.student_id}/recommendations/{rec.id}/notebook-chat"
                )

        return RecommendedExerciseRead.model_validate(rec)

    async def _get_owned_recommendation(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID,
    ) -> RecommendedExercise:
        """Résolution + contrôle d'accès self commun à request_video_overview/ask_notebook_chat."""
        recommendation = await self._recommendation_repo.get_by_id(recommendation_id)
        if recommendation is None:
            raise RecommendationNotFoundError(recommendation_id)
        if recommendation.student_id != requesting_student_id:
            raise ForbiddenError(
                "Un étudiant ne peut agir que sur ses propres recommandations."
            )
        return recommendation

    async def request_video_overview(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID,
    ) -> dict:
        """
        Video Overview À LA DEMANDE — jamais automatique (cf. docstring
        notebooklm_tasks.py). Précondition : un notebook doit déjà exister
        pour cette recommandation (créé de façon best-effort par la Partie
        1/2) — NotebookNotFoundError (404) sinon, jamais une création
        silencieuse ici (contrainte explicite du ticket).

        Dédoublonnage (chantier "régénération NotebookLM", comportement
        changé) : seul un statut déjà PENDING bloque un nouvel appel (une
        génération en cours n'est jamais dupliquée par une deuxième tâche
        Celery concurrente) — READY et FAILED redéclenchent désormais une
        vraie régénération, c'est tout l'intérêt de pouvoir régénérer une
        vidéo déjà prête ou ratée. Avant ce chantier, seul NOT_REQUESTED
        déclenchait une génération (READY/FAILED renvoyaient l'état
        existant sans jamais pouvoir régénérer).
        """
        from app.tasks.notebooklm_tasks import generate_video_overview_task

        recommendation = await self._get_owned_recommendation(requesting_student_id, recommendation_id)
        if recommendation.student_notebook_id is None:
            raise NotebookNotFoundError(recommendation_id)

        notebook = await self._student_notebook_repo.get_by_id(recommendation.student_notebook_id)
        if notebook is None:
            raise NotebookNotFoundError(recommendation_id)

        if notebook.video_overview_status != VideoOverviewStatus.PENDING:
            await self._student_notebook_repo.update_video_overview_status(
                notebook.id, VideoOverviewStatus.PENDING,
            )
            generate_video_overview_task.delay(
                student_notebook_id=str(notebook.id), notebook_id=notebook.notebook_id,
            )
            status = VideoOverviewStatus.PENDING
            video_path = None
        else:
            status = notebook.video_overview_status
            video_path = notebook.video_overview_path

        video_url = (
            self._storage.generate_read_url(StorageContainer.NOTEBOOKLM, video_path)
            if video_path else None
        )
        return {"video_overview_status": status.value, "video_overview_url": video_url}

    async def regenerate_audio_overview(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID,
    ) -> dict:
        """
        Régénération Audio Overview À LA DEMANDE (chantier "régénération
        NotebookLM") — même contrat que request_video_overview : précondition
        notebook existant (NotebookNotFoundError sinon), dédoublonnage
        uniquement contre PENDING (READY/FAILED/NOT_REQUESTED redéclenchent
        tous une régénération réelle, jamais une deuxième tâche concurrente).
        """
        from app.tasks.notebooklm_tasks import regenerate_audio_overview_task

        recommendation = await self._get_owned_recommendation(requesting_student_id, recommendation_id)
        if recommendation.student_notebook_id is None:
            raise NotebookNotFoundError(recommendation_id)

        notebook = await self._student_notebook_repo.get_by_id(recommendation.student_notebook_id)
        if notebook is None:
            raise NotebookNotFoundError(recommendation_id)

        if notebook.audio_overview_status != GenerationStatus.PENDING:
            await self._student_notebook_repo.update_audio_overview_status(
                notebook.id, GenerationStatus.PENDING,
            )
            regenerate_audio_overview_task.delay(
                student_notebook_id=str(notebook.id), notebook_id=notebook.notebook_id,
            )
            status = GenerationStatus.PENDING
            audio_path = None
        else:
            status = notebook.audio_overview_status
            audio_path = notebook.audio_overview_path

        audio_url = (
            self._storage.generate_read_url(StorageContainer.NOTEBOOKLM, audio_path)
            if audio_path else None
        )
        return {"audio_overview_status": status.value, "audio_overview_url": audio_url}

    async def regenerate_flashcards(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID,
    ) -> dict:
        """
        Régénération Flashcards À LA DEMANDE (chantier "régénération
        NotebookLM") — même contrat que regenerate_audio_overview, PLUS
        une revérification d'éligibilité : relit le profil de compétences
        ACTUEL (get_report, jamais les dicts figés de la génération
        initiale — un étudiant peut avoir résorbé ou développé de
        nouvelles difficultés depuis) et refuse (FlashcardsNotEligibleError,
        422) si aucune weakness/identified_difficulty réelle n'existe sur
        AUCUNE compétence du module — jamais de flashcards génériques,
        même règle que la génération initiale (cf. docstring
        notebooklm_tasks.py, _has_real_weakness_data).
        """
        from app.tasks.notebooklm_tasks import regenerate_flashcards_task

        recommendation = await self._get_owned_recommendation(requesting_student_id, recommendation_id)
        if recommendation.student_notebook_id is None:
            raise NotebookNotFoundError(recommendation_id)

        notebook = await self._student_notebook_repo.get_by_id(recommendation.student_notebook_id)
        if notebook is None:
            raise NotebookNotFoundError(recommendation_id)

        if notebook.flashcards_status != GenerationStatus.PENDING:
            report = await self._competency_service.get_report(
                student_id=recommendation.student_id, module_id=recommendation.module_id,
            )
            if not any(line.weaknesses or line.identified_difficulties for line in report.lines):
                raise FlashcardsNotEligibleError(recommendation_id)

            await self._student_notebook_repo.update_flashcards_status(
                notebook.id, GenerationStatus.PENDING,
            )
            regenerate_flashcards_task.delay(
                student_notebook_id=str(notebook.id), notebook_id=notebook.notebook_id,
            )
            status = GenerationStatus.PENDING
            flashcards_path = None
        else:
            status = notebook.flashcards_status
            flashcards_path = notebook.flashcards_path

        flashcards_url = "/demo-flashcards.json" if flashcards_path else None
        return {"flashcards_status": status.value, "flashcards_url": flashcards_url}

    async def ask_notebook_chat(
        self, requesting_student_id: uuid.UUID, recommendation_id: uuid.UUID, question: str,
    ) -> str:
        """
        Proxy synchrone vers NotebookLM (§7, Partie 2/2, accès chat) —
        jamais un lien Google direct exposé (cf. docstring NotebookLMService).
        Chemin SYNCHRONE, pas best-effort silencieux : NotebookLMUnavailable
        Error (503) sur tout échec réel, l'étudiant attend activement une
        réponse.
        """
        recommendation = await self._get_owned_recommendation(requesting_student_id, recommendation_id)
        if recommendation.student_notebook_id is None:
            raise NotebookNotFoundError(recommendation_id)

        notebook = await self._student_notebook_repo.get_by_id(recommendation.student_notebook_id)
        if notebook is None:
            raise NotebookNotFoundError(recommendation_id)

        if is_demo_notebook(notebook.notebook_id):
            return chat_answer(question)

        answer = await self._notebooklm.ask_chat(notebook.notebook_id, question)
        if answer is None:
            raise NotebookLMUnavailableError(notebook.notebook_id)
        return answer

    async def create_recommendation(
        self,
        submission_id: uuid.UUID,
        exercise_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        reason: str,
        relevance_score: Decimal,
        requesting_professor_id: uuid.UUID,
    ) -> RecommendedExerciseRead:
        """
        Point d'écriture CRUD hérité — student_id/module_id ne sont plus des
        paramètres libres (cf. schéma étendu, docstring module) : dérivés
        ici de submission_id/exercise_id (jamais devinés par l'appelant),
        category fixée à REMEDIATION (seule catégorie sensée pour une
        recommandation manuelle explicite — VERIFICATION n'a de sens que
        dérivée d'un confidence_level, absent de ce chemin).

        Fermeture de la faille d'accès (chantier Recommendation_Agent,
        Phase 3) — jusqu'ici accessible à n'importe quel rôle authentifié
        (`get_current_user` côté routeur) : requesting_professor_id doit
        désormais RÉELLEMENT enseigner le module de l'exercice ciblé, même
        contrôle que get_report_as_professor (ExerciseRepository.
        exists_professor_exercise_in_module, seul proxy réel disponible,
        cf. son docstring) — jamais un rôle PROFESSOR suffisant seul.
        """
        if not (Decimal("0") <= relevance_score <= Decimal("1")):
            raise InvalidRelevanceScoreError(relevance_score)

        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)
        exercise = await self._exercise_repo.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        has_exercise_in_module = await self._exercise_repo.exists_professor_exercise_in_module(
            professor_id=requesting_professor_id, module_id=exercise.module_id,
        )
        if not has_exercise_in_module:
            raise ForbiddenError(
                f"Le professeur {requesting_professor_id} n'a aucun exercice "
                f"dans le module {exercise.module_id}."
            )

        recommendation = await self._recommendation_repo.create(
            student_id=submission.student_id,
            module_id=exercise.module_id,
            competency_code=competency_code,
            category=RecommendationCategory.REMEDIATION,
            submission_id=submission_id,
            exercise_id=exercise_id,
            reason=reason,
            relevance_score=relevance_score,
        )
        return await self._to_recommendation_read(recommendation)

    async def get_student_dashboard(self, student_id: uuid.UUID) -> list[RecommendedExerciseRead]:
        recommendations = await self._recommendation_repo.list_active_by_student(student_id)
        result: list[RecommendedExerciseRead] = []
        for rec in recommendations:
            result.append(await self._to_recommendation_read(rec))
        return result

    async def get_student_dashboard_for_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[RecommendedExerciseRead]:
        """
        Traçabilité professeur (clôture du chantier Recommendation_Agent) —
        vue scopée à UN module (jamais tous modules confondus, cf. docstring
        repository), commune au self étudiant et à get_student_dashboard_as_
        professor() ci-dessous, même principe que CompetencyAssessmentService.
        get_report()/get_report_as_professor().
        """
        recommendations = await self._recommendation_repo.list_active_by_student_and_module(
            student_id=student_id, module_id=module_id,
        )
        result: list[RecommendedExerciseRead] = []
        for rec in recommendations:
            result.append(await self._to_recommendation_read(rec))
        return result

    async def get_student_dashboard_as_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[RecommendedExerciseRead]:
        """Même contrôle d'accès que CompetencyAssessmentService.get_report_as_professor — ForbiddenError sinon."""
        has_exercise_in_module = await self._exercise_repo.exists_professor_exercise_in_module(
            professor_id=professor_id, module_id=module_id,
        )
        if not has_exercise_in_module:
            raise ForbiddenError(
                f"Le professeur {professor_id} n'a aucun exercice dans le module {module_id}."
            )
        return await self.get_student_dashboard_for_module(student_id, module_id)

    async def list_by_submission(self, submission_id: uuid.UUID) -> list[RecommendedExerciseRead]:
        """
        Recommandations d'UNE soumission précise, entièrement aplaties
        (exercise_title/difficulty_level/formats NotebookLM) — même
        transformation que get_student_dashboard_for_module, scopée par
        submission_id plutôt que (student_id, module_id) (cf. Recommended
        ExerciseRepository.list_by_submission). Utilisé par feedback_node.py
        (chantier Feedback_Agent) pour reconstruire le payload Celery
        NotebookLM sans dupliquer la logique d'aplatissement.
        """
        recommendations = await self._recommendation_repo.list_by_submission(submission_id)
        result: list[RecommendedExerciseRead] = []
        for rec in recommendations:
            result.append(await self._to_recommendation_read(rec))
        return result

    async def _build_library_coverage(self, module_id: uuid.UUID) -> list[ExerciseCompetencyCoverage]:
        """
        Toute la Library du module (toutes les pages — jamais une troncature
        silencieuse de la couverture disponible), regroupée en compétences
        RÉELLEMENT couvertes par au moins une Question (covered_subquestions
        déjà posé par le pipeline amont, jamais redeviné ici). covered_
        subquestions (union brute, toutes questions confondues) et
        difficulty_level (peut être None si jamais archivé avec difficulté —
        cf. docstring ExerciseCompetencyCoverage) portés tels quels pour le
        matching fin/la préférence de difficulté de l'agent (clôture).
        """
        coverage: list[ExerciseCompetencyCoverage] = []
        cursor: str | None = None
        while True:
            page = await self._exercise_repo.list_library_by_module(module_id, cursor=cursor, limit=100)
            for exercise in page.items:
                competencies: set[C2PCTSkillCode] = set()
                subquestions: set[str] = set()
                for question in exercise.questions:
                    for subquestion_id in question.covered_subquestions or []:
                        subquestions.add(subquestion_id)
                        competency = get_competency_for_subquestion(subquestion_id)
                        if competency is not None:
                            competencies.add(competency)
                if competencies:
                    coverage.append(ExerciseCompetencyCoverage(
                        exercise_id=exercise.id, exercise_title=exercise.title,
                        competencies=frozenset(competencies),
                        covered_subquestions=frozenset(subquestions),
                        difficulty_level=(
                            exercise.difficulty_level.value if exercise.difficulty_level else None
                        ),
                    ))
            if not page.has_more:
                break
            cursor = page.next_cursor
        return coverage

    async def _exclude_fully_succeeded(
        self, student_id: uuid.UUID, coverage: list[ExerciseCompetencyCoverage],
    ) -> list[ExerciseCompetencyCoverage]:
        """
        Historique des soumissions (clôture) — retire de `coverage` tout
        exercice où l'étudiant a déjà une soumission EVALUATED à score
        PLEIN (score total = somme des Bareme.points de l'exercice, jamais
        un seuil arbitraire type "80%"). Un score partiel n'exclut rien
        (remédiation légitime, cf. docstring module).
        """
        exercise_ids = [cov.exercise_id for cov in coverage]
        submissions = await self._submission_repo.list_evaluated_by_student_and_exercise_ids(
            student_id=student_id, exercise_ids=exercise_ids,
        )
        if not submissions:
            return coverage

        fully_succeeded: set[uuid.UUID] = set()
        for submission in submissions:
            if submission.exercise_id in fully_succeeded:
                continue
            exercise = await self._exercise_repo.get_by_id(submission.exercise_id)
            if exercise is None:
                continue
            total_bareme = sum(
                (q.max_points for q in exercise.questions),
                start=Decimal("0"),
            )
            if total_bareme <= 0:
                continue
            total_score = await self._evaluation_repo.get_total_score_for_submission(submission.id)
            if total_score >= total_bareme:
                fully_succeeded.add(submission.exercise_id)

        if not fully_succeeded:
            return coverage
        return [cov for cov in coverage if cov.exercise_id not in fully_succeeded]

    async def generate_recommendations(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        competency_lines: list[CompetencyProfileLine],
        submission_id: uuid.UUID | None = None,
    ) -> list[RecommendedExerciseRead]:
        """
        Point d'entrée réel du Recommendation_Agent — competency_lines
        fourni par l'appelant (StudentCompetencyReport.lines,
        CompetencyAssessmentService.get_report), jamais recalculé ici.
        """
        library_coverage = await self._build_library_coverage(module_id)
        library_coverage = await self._exclude_fully_succeeded(student_id, library_coverage)

        recommendation_set = RecommendationAgent.generate(
            student_id=student_id, module_id=module_id,
            competency_lines=competency_lines, library_coverage=library_coverage,
            generated_at=datetime.now(timezone.utc),
            weak_mastery_threshold=self._settings.RECOMMENDATION_WEAK_MASTERY_THRESHOLD,
            low_confidence_threshold=self._settings.RECOMMENDATION_LOW_CONFIDENCE_THRESHOLD,
            max_per_competency=self._settings.RECOMMENDATION_MAX_PER_COMPETENCY,
            max_total=self._settings.RECOMMENDATION_MAX_TOTAL,
        )

        # Dédoublonnage — supersède les ACTIVE existantes de TOUTE compétence
        # présente dans ce rapport (pas seulement celles qui produisent une
        # NOUVELLE recommandation) : une compétence qui n'est plus faible
        # doit voir son ancienne recommandation supersédée même si le
        # nouveau passage n'en régénère aucune pour elle — sinon une
        # recommandation obsolète ("tu es faible en X") resterait ACTIVE
        # indéfiniment après que X soit résolue. Toujours AVANT d'insérer
        # les nouvelles (jamais un empilement infini à chaque soumission
        # notée, cf. docstring module).
        touched_competencies = {line.competency for line in competency_lines}
        for competency in touched_competencies:
            existing = await self._recommendation_repo.list_active_by_student_module_competency(
                student_id=student_id, module_id=module_id, competency_code=competency,
            )
            await self._recommendation_repo.supersede([e.id for e in existing])

        results: list[RecommendedExerciseRead] = []
        for rec in recommendation_set.recommendations:
            created = await self._recommendation_repo.create(
                student_id=student_id, module_id=module_id,
                competency_code=rec.competency, category=RecommendationCategory(rec.category),
                exercise_id=rec.exercise_id, reason=rec.reason,
                relevance_score=rec.relevance_score, submission_id=submission_id,
            )
            results.append(await self._to_recommendation_read(created))
        return results


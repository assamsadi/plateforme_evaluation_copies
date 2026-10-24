import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_competency_assessment_service,
    get_current_professor,
    get_current_student,
    get_current_user,
    get_evaluation_service,
    get_feedback_report_service,
    get_feedback_service,
    get_grade_appeal_service,
    get_recommendation_service,
    get_statistics_service,
)
from app.domain.models.identity.user import User, UserRole, Student
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.arbitration_schemas import (
    GradeAppealCreate,
    GradeAppealRead,
    GradeAppealResolutionRequest,
)
from app.domain.schemas.evaluation_schemas import (
    AudioOverviewStateRead,
    EvaluationRead,
    FeedbackReportRead,
    FeedbackVersionRead,
    FlashcardsStateRead,
    NotebookChatRequest,
    NotebookChatResponse,
    RecommendedExerciseRead,
    StudentModuleSummaryRead,
    SubmissionResultRead,
    VideoOverviewStateRead,
)
from app.domain.schemas.c2pct_schemas import CompetencyObservationRead, StudentModuleOptionRead
from app.core.exceptions import ForbiddenError
from app.services.competency_assessment_service import CompetencyAssessmentService
from app.services.evaluation_service import EvaluationService
from app.services.feedback_report_service import FeedbackReportService
from app.services.feedback_service import FeedbackService
from app.services.grade_appeal_service import GradeAppealService
from app.services.recommendation_service import RecommendationService
from app.services.statistics_service import StatisticsService

router = APIRouter(tags=["results, evaluations & appeals"])


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationRead)
async def get_evaluation(
    evaluation_id: uuid.UUID,
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Bug corrigé (audit résultats professeur) : appelait evaluation_service.
    get_evaluation(evaluation_id), méthode inexistante sur EvaluationService
    (AttributeError -> 500 à chaque appel, masqué en test par un AsyncMock
    nu). Faille de contrôle d'accès corrigée dans le même passage — cf.
    docstring EvaluationService._authorize_submission_access.
    """
    return await evaluation_service.get_evaluation(evaluation_id, current_user)


@router.get("/submissions/{submission_id}/evaluations", response_model=list[EvaluationRead])
async def list_evaluations_for_submission(
    submission_id: uuid.UUID,
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Bug corrigé (audit résultats professeur) : appelait evaluation_service.
    list_evaluations_by_submission(submission_id), méthode inexistante
    (AttributeError -> 500 à chaque appel, même masquage par AsyncMock nu
    que get_evaluation ci-dessus). Faille de contrôle d'accès corrigée dans
    le même passage.
    """
    return await evaluation_service.list_evaluations_for_submission(submission_id, current_user)


@router.get("/submissions/{submission_id}/copy-report")
async def get_submission_copy_report(
    submission_id: uuid.UUID,
    current_prof: Annotated[User, Depends(get_current_professor)],
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
):
    """
    Gap trouvé lors de l'audit résultats professeur : EvaluationService.
    get_copy_report existait déjà (agrégat "questions ambiguës / à revoir /
    consigne non respectée") mais n'était exposé par AUCUN endpoint. Pas de
    response_model : CopyReport est un dataclass (cf. StudentCompetencyReport
    ci-dessus, même convention), jamais un schéma Pydantic dédié pour ce
    format déjà stable.
    """
    return await evaluation_service.get_copy_report_for_professor(submission_id, current_prof.id)


@router.get("/submissions/{submission_id}/feedback", response_model=FeedbackReportRead)
async def get_submission_feedback_as_professor(
    submission_id: uuid.UUID,
    current_prof: Annotated[User, Depends(get_current_professor)],
    feedback_report_service: Annotated[FeedbackReportService, Depends(get_feedback_report_service)],
):
    """
    Gap trouvé (chantier "notation vivante", écran de détail de notation
    refondu) — le texte socratique de Feedback_Agent n'était consultable
    que par l'étudiant lui-même (cf. GET /students/{id}/submissions/{id}/
    feedback ci-dessous, explicitement self-only). Réservé au professeur
    créateur de l'exercice, même garde que /copy-report ci-dessus.
    FeedbackReportNotFoundError (404) si feedback_node n'a pas encore
    traité cette soumission.
    """
    return await feedback_report_service.get_by_submission_as_professor(submission_id, current_prof.id)


@router.get("/evaluations/{evaluation_id}/feedbacks", response_model=list[FeedbackVersionRead])
async def list_feedbacks_for_evaluation(
    evaluation_id: uuid.UUID,
    feedback_service: Annotated[FeedbackService, Depends(get_feedback_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await feedback_service.list_versions_by_evaluation(evaluation_id)


@router.post("/appeals", response_model=GradeAppealRead, status_code=status.HTTP_201_CREATED)
async def submit_grade_appeal(
    schema: GradeAppealCreate,
    current_student: Annotated[Student, Depends(get_current_student)],
    appeal_service: Annotated[GradeAppealService, Depends(get_grade_appeal_service)],
):
    return await appeal_service.file_appeal(
        submission_id=schema.submission_id,
        student_id=current_student.id,
        reason=schema.reason,
        evaluation_id=schema.evaluation_id,
        extraction_correction_id=schema.extraction_correction_id,
    )


@router.get("/submissions/{submission_id}/appeals", response_model=list[GradeAppealRead])
async def list_my_appeals_for_submission(
    submission_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    appeal_service: Annotated[GradeAppealService, Depends(get_grade_appeal_service)],
):
    """
    Gap fermé (espace étudiant) : POST /appeals existait déjà, mais rien
    ne permettait à l'étudiant de revoir le statut/la résolution d'une
    contestation qu'il a déposée — cf. docstring GradeAppealService.
    list_by_submission_for_student.
    """
    return await appeal_service.list_by_submission_for_student(
        submission_id=submission_id, requesting_student_id=current_student.id,
    )


@router.get("/appeals/pending", response_model=CursorPage[GradeAppealRead])
async def list_pending_appeals(
    appeal_service: Annotated[GradeAppealService, Depends(get_grade_appeal_service)],
    current_prof: Annotated[User, Depends(get_current_professor)],
    cursor: str | None = None,
    limit: int = 50,
):
    # Déclaré avant tout futur /appeals/{appeal_id} pour éviter le même
    # piège de parsing UUID que /courses/mine vs /courses/{course_id}.
    return await appeal_service.list_pending_for_professor(current_prof.id, cursor=cursor, limit=limit)


@router.post("/appeals/{appeal_id}/resolve", response_model=GradeAppealRead)
async def resolve_grade_appeal(
    appeal_id: uuid.UUID,
    schema: GradeAppealResolutionRequest,
    current_prof: Annotated[User, Depends(get_current_professor)],
    appeal_service: Annotated[GradeAppealService, Depends(get_grade_appeal_service)],
):
    return await appeal_service.resolve_appeal(
        appeal_id=appeal_id,
        requesting_professor_id=current_prof.id,
        resolution=schema.resolution,
        review_comment=schema.review_comment,
        revised_score=schema.revised_score,
    )


@router.get("/students/me/submissions/{submission_id}/results", response_model=SubmissionResultRead)
async def get_my_submission_results(
    submission_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
):
    """
    Écran dédié "Mes résultats" (gap fermé, test réel 2026-08-31) — un
    étudiant pouvait voir sa soumission passer à EVALUATED sans jamais voir
    sa note nulle part (aucun champ total_score sur SubmissionRead
    étudiant, et /submissions/{id}/copy-report est réservé au professeur,
    cf. son docstring). Distinct de ce dernier : ici seulement score/barème
    par question + total, jamais les justifications techniques internes.
    """
    return await evaluation_service.get_results_for_student(submission_id, current_student.id)


@router.get("/students/me/stats")
async def get_my_statistics(
    current_student: Annotated[Student, Depends(get_current_student)],
    stats_service: Annotated[StatisticsService, Depends(get_statistics_service)],
):
    return await stats_service.get_student_stats(current_student.id)


@router.get("/students/me/competency-profile")
async def get_my_competency_profile(
    module_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    competency_service: Annotated[CompetencyAssessmentService, Depends(get_competency_assessment_service)],
):
    """
    Correctif découvertes annexes (priorité 3) — alias "self" pratique de
    GET /students/{student_id}/competency-profile (même service, même
    StudentCompetencyReport), pas une logique dupliquée : plantait
    auparavant en 500 (StatisticsService.get_student_competency_profile
    appelait competency_profile_repo.get_by_student, méthode inexistante,
    et lisait p.skill_code/p.last_evaluated_at, champs inexistants sur le
    modèle — code jamais exercé en pratique, cf. rapport de câblage).
    module_id requis : la donnée est scopée par module (StudentCompetency
    Observation/Profile n'ont jamais de vue "tous modules confondus"),
    jamais un agrégat inter-modules deviné ici.
    """
    return await competency_service.get_report(uuid.UUID(str(current_student.id)), module_id)


@router.get("/students/{student_id}/competency-modules", response_model=list[StudentModuleOptionRead])
async def list_student_competency_modules(
    student_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    competency_service: Annotated[CompetencyAssessmentService, Depends(get_competency_assessment_service)],
):
    """
    Écran "Profil de compétence" (sélecteur de module) — gap fermé (test
    réel, 2026-08-31). PAS sourcé depuis Enrollment (un étudiant réel s'est
    révélé sans aucune ligne Enrollment malgré des copies notées, accès à
    l'examen via groupe de cours — cf. docstring StudentCompetencyProfile
    Repository.list_distinct_modules_by_student pour le détail) : seuls les
    modules où un vrai profil de compétence existe déjà apparaissent ici.
    Même garde d'accès dual rôle que /competency-profile ci-dessous.
    """
    current_user_id = uuid.UUID(str(current_user.id))

    if current_user.role == UserRole.STUDENT:
        if current_user_id != student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que ses propres modules.")
        return await competency_service.list_student_modules(student_id)

    if current_user.role == UserRole.PROFESSOR:
        return await competency_service.list_student_modules_as_professor(
            professor_id=current_user_id, student_id=student_id,
        )

    raise ForbiddenError("Accès à la liste des modules réservé à l'étudiant concerné ou à ses professeurs.")


@router.get("/students/{student_id}/competency-profile")
async def get_student_competency_profile(
    student_id: uuid.UUID,
    module_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    competency_service: Annotated[CompetencyAssessmentService, Depends(get_competency_assessment_service)],
):
    """
    Câblage Partie 2/2 (chantier C2PCT) — profil de compétences réel
    (StudentCompetencyReport, Competency_Assessment_Agent), distinct de
    /students/me/competency-profile (endpoint pré-existant, cassé — cf.
    rapport de câblage, StatisticsService.get_student_competency_profile
    appelle une méthode de repository inexistante — hors mandat, non touché
    ici).

    Contrôle d'accès : un étudiant ne peut consulter que son propre profil ;
    un professeur peut consulter le profil de n'importe quel étudiant dans
    un module où il a créé au moins un exercice (CompetencyAssessmentService.
    get_report_as_professor, seul proxy réel d'ownership module disponible
    dans ce schéma) ; tout autre cas -> 403 (ForbiddenError, mappée
    globalement par app/main.py). Comparaisons/normalisation via str(...) ->
    uuid.UUID(...) plutôt qu'une égalité directe : current_user.id est un
    vrai uuid.UUID en production (User ORM, cf. get_current_user), mais
    rester robuste à un id porté comme str ailleurs coûte rien et évite un
    faux 403 par simple différence de type.
    """
    current_user_id = uuid.UUID(str(current_user.id))

    if current_user.role == UserRole.STUDENT:
        if current_user_id != student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que son propre profil de compétences.")
        return await competency_service.get_report(student_id, module_id)

    if current_user.role == UserRole.PROFESSOR:
        return await competency_service.get_report_as_professor(
            professor_id=current_user_id, student_id=student_id, module_id=module_id,
        )

    raise ForbiddenError("Accès au profil de compétences réservé à l'étudiant concerné ou à ses professeurs.")


@router.get("/students/{student_id}/competency-history", response_model=list[CompetencyObservationRead])
async def get_student_competency_history(
    student_id: uuid.UUID,
    module_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    competency_service: Annotated[CompetencyAssessmentService, Depends(get_competency_assessment_service)],
):
    """
    Écran "Profil de compétence" (graphique d'évolution dans le temps) —
    série temporelle brute (StudentCompetencyObservation), distincte de
    /competency-profile ci-dessus (agrégat Niveau 3 uniquement). Même garde
    d'accès dual rôle, mot pour mot — jamais une variante réécrite à la main.
    """
    current_user_id = uuid.UUID(str(current_user.id))

    if current_user.role == UserRole.STUDENT:
        if current_user_id != student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que son propre historique de compétences.")
        return await competency_service.get_observation_history(student_id, module_id)

    if current_user.role == UserRole.PROFESSOR:
        return await competency_service.get_observation_history_as_professor(
            professor_id=current_user_id, student_id=student_id, module_id=module_id,
        )

    raise ForbiddenError("Accès à l'historique de compétences réservé à l'étudiant concerné ou à ses professeurs.")


@router.get("/students/{student_id}/module-summary", response_model=StudentModuleSummaryRead)
async def get_student_module_summary(
    student_id: uuid.UUID,
    module_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
):
    """
    Écran "Profil de compétence" (bloc infos étudiant) — copies déposées/
    notées + note générale pour CE module. Même garde d'accès dual rôle que
    /competency-profile et /competency-history ci-dessus, mot pour mot.
    """
    current_user_id = uuid.UUID(str(current_user.id))

    if current_user.role == UserRole.STUDENT:
        if current_user_id != student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que son propre résumé de module.")
        return await evaluation_service.get_module_summary_for_student(student_id, module_id)

    if current_user.role == UserRole.PROFESSOR:
        return await evaluation_service.get_module_summary_as_professor(
            professor_id=current_user_id, student_id=student_id, module_id=module_id,
        )

    raise ForbiddenError("Accès au résumé de module réservé à l'étudiant concerné ou à ses professeurs.")


@router.get("/students/{student_id}/recommendations", response_model=list[RecommendedExerciseRead])
async def get_student_recommendations(
    student_id: uuid.UUID,
    module_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    recommendation_service: Annotated[RecommendationService, Depends(get_recommendation_service)],
):
    """
    Traçabilité professeur (clôture du chantier Recommendation_Agent) —
    exact même contrôle d'accès que GET /students/{student_id}/competency-
    profile ci-dessus (self étudiant, ou professeur ayant au moins un
    exercice dans ce module) : un professeur pouvait créer une recommandation
    manuelle (POST /library/recommendations, Phase 3) sans jamais pouvoir
    voir l'état actuel des recommandations d'un étudiant — trou fermé ici.
    Scopé par module (jamais "tous modules confondus" pour un professeur,
    cf. docstring RecommendedExerciseRepository.list_active_by_student_and_
    module) ; l'étudiant garde par ailleurs sa vue tous-modules existante
    via GET /library/recommendations (self, inchangée).
    """
    current_user_id = uuid.UUID(str(current_user.id))

    if current_user.role == UserRole.STUDENT:
        if current_user_id != student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que ses propres recommandations.")
        return await recommendation_service.get_student_dashboard_for_module(student_id, module_id)

    if current_user.role == UserRole.PROFESSOR:
        return await recommendation_service.get_student_dashboard_as_professor(
            professor_id=current_user_id, student_id=student_id, module_id=module_id,
        )

    raise ForbiddenError("Accès aux recommandations réservé à l'étudiant concerné ou à ses professeurs.")


@router.post(
    "/students/{student_id}/recommendations/{recommendation_id}/generate-video",
    response_model=VideoOverviewStateRead,
)
async def generate_recommendation_video_overview(
    student_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    recommendation_service: Annotated[RecommendationService, Depends(get_recommendation_service)],
):
    """
    Video Overview À LA DEMANDE (§7, Partie 2/2) — réservé à l'étudiant
    lui-même, JAMAIS un professeur (get_current_student exclut déjà tout
    autre rôle ; la comparaison ci-dessous vérifie en plus que student_id
    dans l'URL correspond bien à l'appelant, même garde-fou que
    get_student_recommendations ci-dessus). Précondition : un notebook
    doit déjà exister pour cette recommandation (NotebookNotFoundError ->
    404 sinon, cf. docstring service — jamais une création silencieuse
    ici). Sert aussi de RÉGÉNÉRATION (chantier "régénération NotebookLM") :
    dédoublonnage géré par le service uniquement contre PENDING (une
    génération déjà en cours n'est jamais dupliquée) — un appel depuis
    READY ou FAILED redéclenche désormais une vraie régénération, jamais
    un simple renvoi de l'état existant.
    """
    current_student_id = uuid.UUID(str(current_student.id))
    if current_student_id != student_id:
        raise ForbiddenError("Un étudiant ne peut demander une vidéo que pour son propre compte.")

    return await recommendation_service.request_video_overview(
        requesting_student_id=current_student_id, recommendation_id=recommendation_id,
    )


@router.post(
    "/students/{student_id}/recommendations/{recommendation_id}/regenerate-audio",
    response_model=AudioOverviewStateRead,
)
async def regenerate_recommendation_audio_overview(
    student_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    recommendation_service: Annotated[RecommendationService, Depends(get_recommendation_service)],
):
    """
    Régénération Audio Overview À LA DEMANDE (chantier "régénération
    NotebookLM") — même garde self-only que generate-video ci-dessus.
    Précondition : un notebook doit déjà exister (NotebookNotFoundError ->
    404 sinon). Dédoublonnage uniquement contre PENDING, cf. docstring
    RecommendationService.regenerate_audio_overview.
    """
    current_student_id = uuid.UUID(str(current_student.id))
    if current_student_id != student_id:
        raise ForbiddenError("Un étudiant ne peut régénérer un audio que pour son propre compte.")

    return await recommendation_service.regenerate_audio_overview(
        requesting_student_id=current_student_id, recommendation_id=recommendation_id,
    )


@router.post(
    "/students/{student_id}/recommendations/{recommendation_id}/regenerate-flashcards",
    response_model=FlashcardsStateRead,
)
async def regenerate_recommendation_flashcards(
    student_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    recommendation_service: Annotated[RecommendationService, Depends(get_recommendation_service)],
):
    """
    Régénération Flashcards À LA DEMANDE (chantier "régénération
    NotebookLM") — même garde self-only que generate-video ci-dessus.
    Précondition : un notebook doit déjà exister (NotebookNotFoundError ->
    404 sinon). FlashcardsNotEligibleError (422) si aucune weakness/
    identified_difficulty réelle sur le profil ACTUEL de l'étudiant pour
    ce module — jamais de flashcards génériques, cf. docstring
    RecommendationService.regenerate_flashcards.
    """
    current_student_id = uuid.UUID(str(current_student.id))
    if current_student_id != student_id:
        raise ForbiddenError("Un étudiant ne peut régénérer des flashcards que pour son propre compte.")

    return await recommendation_service.regenerate_flashcards(
        requesting_student_id=current_student_id, recommendation_id=recommendation_id,
    )


@router.post(
    "/students/{student_id}/recommendations/{recommendation_id}/notebook-chat",
    response_model=NotebookChatResponse,
)
async def ask_recommendation_notebook_chat(
    student_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    command: NotebookChatRequest,
    current_student: Annotated[Student, Depends(get_current_student)],
    recommendation_service: Annotated[RecommendationService, Depends(get_recommendation_service)],
):
    """
    Accès chat interactif (§7, Partie 2/2) — proxy synchrone vers
    NotebookLM, réservé à l'étudiant lui-même (même garde que ci-dessus).
    JAMAIS un lien Google direct exposé au client (cf. docstring
    NotebookLMService pour la justification complète de ce choix) :
    l'étudiant passe uniquement par notre propre authentification JWT.
    NotebookLMUnavailableError (503) sur tout échec réel — chemin
    synchrone, l'étudiant attend activement une réponse, jamais un succès
    silencieux avec une réponse vide.
    """
    current_student_id = uuid.UUID(str(current_student.id))
    if current_student_id != student_id:
        raise ForbiddenError("Un étudiant ne peut interroger que son propre notebook.")

    answer = await recommendation_service.ask_notebook_chat(
        requesting_student_id=current_student_id, recommendation_id=recommendation_id,
        question=command.question,
    )
    return NotebookChatResponse(answer=answer)


@router.get(
    "/students/{student_id}/submissions/{submission_id}/feedback",
    response_model=FeedbackReportRead,
)
async def get_submission_feedback(
    student_id: uuid.UUID,
    submission_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    feedback_report_service: Annotated[FeedbackReportService, Depends(get_feedback_report_service)],
):
    """
    Feedback pédagogique socratique d'UNE soumission (chantier Feedback_
    Agent, §7) — self-only, même garde que les endpoints vidéo/chat
    NotebookLM ci-dessus (jamais un accès professeur ici, pas demandé par
    le ticket). Aucun endpoint existant n'était scopé à une soumission
    unique avec ce contenu (GET .../recommendations est scopé student+
    module, liste plate par exercice — dupliquer le même texte sur N
    lignes aurait été maladroit, cf. plan validé) : endpoint dédié.
    FeedbackReportNotFoundError (404) si feedback_node n'a pas encore
    traité cette soumission — jamais une génération à la demande ici.
    """
    current_student_id = uuid.UUID(str(current_student.id))
    if current_student_id != student_id:
        raise ForbiddenError("Un étudiant ne peut consulter que son propre feedback.")

    return await feedback_report_service.get_by_submission_for_student(
        submission_id=submission_id, requesting_student_id=current_student_id,
    )

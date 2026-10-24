import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import (
    get_current_professor,
    get_current_student,
    get_current_user,
    get_decision_log_service,
    get_document_structuring_service,
    get_evaluation_service,
    get_exercise_service,
    get_job_supervision_service,
)
from app.core.exceptions import NotExerciseOwnerError
from app.domain.models.identity.user import User, Professor, Student
from app.domain.models.assessment.exercise import ExerciseDifficulty, ExerciseStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.exercise_schemas import (
    BaremeCreate,
    ExerciseArchiveToLibraryRequest,
    ExerciseCreateRequest,
    ExerciseDeadlineUpdateRequest,
    ExercisePublishRequest,
    ExerciseRead,
    PublicationReadinessRead,
    QuestionAddRequest,
    QuestionUpdateRequest,
    SubquestionPointsCreate,
)
from app.domain.schemas.submission_schemas import SubmissionSummaryRead
from app.domain.schemas.system_schemas import AgentDecisionLogRead, JobRead
from app.domain.schemas.teacher_correction_block_schemas import (
    BulkBlockResolutionRequest,
    TeacherCorrectionBlockRead,
)
from app.services.decision_log_service import DecisionLogService
from app.services.document_structuring_service import DocumentStructuringService
from app.services.evaluation_service import EvaluationService
from app.services.exercise_service import ExerciseService
from app.services.job_supervision_service import JobSupervisionService

router = APIRouter(tags=["exercises"])


@router.get("/exercises/mine", response_model=CursorPage[ExerciseRead])
async def list_my_exercises(
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    cursor: str | None = None,
    limit: int = 50,
):
    # Déclaré avant /exercises/{exercise_id} pour éviter le même piège de
    # parsing UUID que /courses/mine vs /courses/{course_id}.
    return await exercise_service.list_by_professor(current_prof.id, cursor=cursor, limit=limit)


@router.get("/students/me/assigned-exercises", response_model=CursorPage[ExerciseRead])
async def list_my_assigned_exercises(
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
    current_student: Annotated[Student, Depends(get_current_student)],
    cursor: str | None = None,
    limit: int = 50,
):
    """
    Gap fermé (espace étudiant) : ExerciseRepository.
    list_published_exams_for_student existait déjà mais n'était appelée par
    aucun service/endpoint — un étudiant n'avait aucun moyen de découvrir
    quels examens/devoirs publiés lui sont assignés (distinct de la
    bibliothèque GET /modules/{id}/library, pratique libre uniquement).
    """
    return await exercise_service.list_assigned_for_student(current_student.id, cursor=cursor, limit=limit)


@router.get("/exercises/{exercise_id}", response_model=ExerciseRead)
async def get_exercise(
    exercise_id: uuid.UUID,
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await exercise_service.get_by_id(exercise_id)


@router.delete("/exercises/{exercise_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exercise(
    exercise_id: uuid.UUID,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Gap trouvé lors de l'audit authoring : aucun endpoint ne permettait de
    supprimer un exercice, même un DRAFT créé par erreur. Verrous stricts
    dans ExerciseService.delete() (propriétaire, DRAFT uniquement, aucune
    Submission) — jamais un exercice publié ou ayant déjà reçu une copie.
    """
    await exercise_service.delete(exercise_id, current_prof.id)


@router.get("/courses/{course_id}/exercises", response_model=CursorPage[ExerciseRead])
async def list_exercises_by_course(
    course_id: uuid.UUID,
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: int = 50,
):
    return await exercise_service.list_by_course(course_id=course_id, cursor=cursor, limit=limit)


@router.get("/modules/{module_id}/library", response_model=CursorPage[ExerciseRead])
async def list_module_library(
    module_id: uuid.UUID,
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    competency: C2PCTSkillCode | None = None,
    difficulty: ExerciseDifficulty | None = None,
    cursor: str | None = None,
    limit: int = 50,
):
    """
    Navigation de la Library (ARCHIVED_IN_LIBRARY) d'un module — câblage
    Recommendation_Agent, Phase 3 + clôture. `competency` optionnel filtre
    aux exercices couvrant réellement cette compétence (cf. docstring
    ExerciseService.list_by_module) ; `difficulty` optionnel filtre par
    Exercise.difficulty_level (colonne réelle, pagination réelle même
    filtrée, contrairement à `competency`) ; combinables. Sans les deux,
    pagination réelle sur toute la Library du module.
    """
    return await exercise_service.list_by_module(
        module_id=module_id, competency=competency, difficulty=difficulty, cursor=cursor, limit=limit,
    )


@router.post("/exercises", response_model=ExerciseRead, status_code=status.HTTP_201_CREATED)
async def create_exercise(
    schema: ExerciseCreateRequest,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    return await exercise_service.create(
        module_id=schema.module_id,
        created_by_professor_id=current_prof.id,
        title=schema.title,
        description=schema.description,
        questions_data=[q.model_dump() for q in schema.questions],
    )


@router.post("/exercises/{exercise_id}/publish", response_model=ExerciseRead)
async def publish_exercise(
    exercise_id: uuid.UUID,
    command: ExercisePublishRequest,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    return await exercise_service.publish(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
        status=command.status,
        course_id=command.course_id,
        deadline=command.deadline,
    )


@router.patch("/exercises/{exercise_id}/deadline", response_model=ExerciseRead)
async def update_exercise_deadline(
    exercise_id: uuid.UUID,
    command: ExerciseDeadlineUpdateRequest,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Report/avance de la date limite d'un examen/devoir déjà publié —
    demande explicite professeur. Distinct de POST .../publish (qui exige
    une nouvelle confirmation de complétude, hors de propos pour un simple
    changement de date) — cf. docstring ExerciseService.update_deadline.
    """
    return await exercise_service.update_deadline(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
        deadline=command.deadline,
    )


@router.post(
    "/exercises/{exercise_id}/confirm-publication-readiness",
    response_model=PublicationReadinessRead,
)
async def confirm_publication_readiness(
    exercise_id: uuid.UUID,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Confirmation professeur explicite, requise par publish() (EXAM/HOMEWORK)
    en plus de la vérification technique de complétude déjà en place.
    Retourne le résumé (barème + variante de référence par question) tel
    que confirmé — invalidée automatiquement si cet état change ensuite.
    """
    return await exercise_service.confirm_publication_readiness(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
    )


@router.post("/exercises/{exercise_id}/archive-to-library", response_model=ExerciseRead)
async def archive_exercise_to_library(
    exercise_id: uuid.UUID,
    command: ExerciseArchiveToLibraryRequest,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Câblage Recommendation_Agent (clôture) — difficulty_level désormais
    obligatoire dans le corps de la requête (cf. docstring
    ExerciseArchiveToLibraryRequest) : MissingDifficultyLevelError -> 422
    si jamais omise (défense en profondeur, le schema Pydantic la rend déjà
    obligatoire au niveau HTTP).
    """
    return await exercise_service.publish(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
        status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
        course_id=None,
        deadline=None,
        difficulty_level=command.difficulty_level,
    )


ALLOWED_REFERENCE_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/tiff",
}


@router.post("/exercises/{exercise_id}/reference-document", response_model=ExerciseRead)
async def upload_exercise_reference_document(
    exercise_id: uuid.UUID,
    document: Annotated[UploadFile, File(description="Document scanné énoncé + correction (PDF ou image)")],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    from app.core.exceptions import ValidationError

    mime_type = (document.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if mime_type not in ALLOWED_REFERENCE_MIME_TYPES:
        raise ValidationError(
            f"Type de fichier non supporté : {mime_type}. "
            f"Formats acceptés : PDF, PNG, JPEG, WEBP, TIFF."
        )

    document_bytes = await document.read()
    if not document_bytes:
        raise ValidationError("Le fichier soumis est vide.")

    return await exercise_service.upload_reference_document(
        exercise_id=exercise_id,
        professor_id=current_prof.id,
        document_bytes=document_bytes,
        mime_type=mime_type,
    )


@router.get("/exercises/{exercise_id}/reference-document-url")
async def get_exercise_reference_document_url(
    exercise_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Retourne l'URL SAS temporaire pour accéder au document de référence de l'exercice.
    Accessible à tout utilisateur pouvant consulter l'exercice (professeur ou étudiant).
    """
    url = await exercise_service.get_reference_document_url(exercise_id, current_user.id)
    if not url:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document de référence non trouvé")
    return {"url": url}


@router.put("/exercises/{exercise_id}/questions/{question_id}/bareme", response_model=ExerciseRead)
async def set_question_bareme(
    exercise_id: uuid.UUID,
    question_id: uuid.UUID,
    schema: BaremeCreate,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Ajout/édition manuelle du barème d'une question après la création de
    l'exercice (gap trouvé lors de l'audit authoring) — seul recours pour un
    professeur ayant créé une question sans barème (ex. en comptant sur
    l'extraction IA) ou souhaitant corriger un barème déjà saisi.
    """
    return await exercise_service.set_question_bareme(
        exercise_id=exercise_id,
        question_id=question_id,
        requesting_professor_id=current_prof.id,
        points=schema.points,
        criteria=[c.model_dump() for c in schema.criteria],
    )


@router.put(
    "/exercises/{exercise_id}/questions/{question_id}/subquestion-points", response_model=ExerciseRead,
)
async def set_question_subquestion_points(
    exercise_id: uuid.UUID,
    question_id: uuid.UUID,
    schema: SubquestionPointsCreate,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Saisie manuelle de secours pour le barème C2PCT natif (Cas 0) — gap
    réel trouvé en usage : set_question_bareme ci-dessus écrit dans le
    barème CLASSIQUE, jamais dans Question.subquestion_points ; un
    professeur corrigeant ainsi une question C2PCT native basculait cette
    question sur le mauvais mécanisme de calcul sans le savoir. Cet
    endpoint écrit directement dans subquestion_points, même mécanisme que
    l'extraction automatique (Extraction_Verification_Agent).
    """
    return await exercise_service.set_question_subquestion_points(
        exercise_id=exercise_id,
        question_id=question_id,
        requesting_professor_id=current_prof.id,
        points=schema.points,
    )


@router.post("/exercises/{exercise_id}/questions", response_model=ExerciseRead, status_code=status.HTTP_201_CREATED)
async def add_question(
    exercise_id: uuid.UUID,
    schema: QuestionAddRequest,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Gap trouvé lors de l'audit CRUD authoring : aucun moyen d'ajouter une
    question à un exercice après sa création initiale. DRAFT uniquement.
    """
    return await exercise_service.add_question(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
        statement=schema.statement,
    )


@router.patch("/exercises/{exercise_id}/questions/{question_id}", response_model=ExerciseRead)
async def update_question(
    exercise_id: uuid.UUID,
    question_id: uuid.UUID,
    schema: QuestionUpdateRequest,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    return await exercise_service.update_question_statement(
        exercise_id=exercise_id,
        question_id=question_id,
        requesting_professor_id=current_prof.id,
        statement=schema.statement,
    )


@router.delete("/exercises/{exercise_id}/questions/{question_id}", response_model=ExerciseRead)
async def delete_question(
    exercise_id: uuid.UUID,
    question_id: uuid.UUID,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
):
    """
    Refuse de supprimer la dernière question restante (MinimumQuestionCount
    Error) — un exercice sans question n'a pas de sens (cf. ExerciseCreate
    Request.questions, min_length=1 à la création).
    """
    return await exercise_service.delete_question(
        exercise_id=exercise_id,
        question_id=question_id,
        requesting_professor_id=current_prof.id,
    )


@router.get("/exercises/{exercise_id}/pipeline-status", response_model=JobRead | None)
async def get_exercise_pipeline_status(
    exercise_id: uuid.UUID,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
    job_supervision_service: Annotated[
        JobSupervisionService, Depends(get_job_supervision_service)
    ],
):
    """
    Gap trouvé lors de l'audit authoring : après un dépôt de document de
    référence, un professeur n'avait aucun moyen de savoir si le pipeline
    OCR tourne encore, a échoué, ou a terminé — seul l'admin dispose de
    /admin/jobs/overview. None si aucun Job n'a jamais été créé pour cet
    exercice (ex. professeur resté 100% manuel).
    """
    exercise = await exercise_service.get_by_id(exercise_id)
    if exercise.created_by_professor_id != current_prof.id:
        raise NotExerciseOwnerError(exercise_id, current_prof.id)

    return await job_supervision_service.get_latest_for_exercise(exercise_id)


@router.get(
    "/exercises/{exercise_id}/correction-blocks",
    response_model=list[TeacherCorrectionBlockRead],
)
async def list_exercise_correction_blocks(
    exercise_id: uuid.UUID,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    structuring_service: Annotated[
        DocumentStructuringService, Depends(get_document_structuring_service)
    ],
):
    """
    Découverte des blocs de correction d'un exercice (gap trouvé lors du
    chantier authoring professeur) — sans cet endpoint, aucun client ne peut
    savoir quels blocs le pipeline OCR a produits ni lesquels restent
    UNRESOLVED_NO_LABEL, rendant /structure/resolve-blocks inutilisable en
    pratique (son payload exige déjà les block_id en question).
    """
    return await structuring_service.list_blocks_for_exercise(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
    )


@router.post(
    "/exercises/{exercise_id}/structure/resolve-blocks",
    response_model=list[TeacherCorrectionBlockRead],
)
async def resolve_unresolved_structuring_blocks(
    exercise_id: uuid.UUID,
    command: BulkBlockResolutionRequest,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    structuring_service: Annotated[
        DocumentStructuringService, Depends(get_document_structuring_service)
    ],
):
    """
    Résolution manuelle HITL par le professeur créateur des blocs de correction UNRESOLVED_NO_LABEL.
    """
    return await structuring_service.resolve_unresolved_blocks(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
        resolutions=command.resolutions,
    )


@router.post(
    "/exercises/{exercise_id}/structure/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def confirm_exercise_structuring(
    exercise_id: uuid.UUID,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    structuring_service: Annotated[
        DocumentStructuringService, Depends(get_document_structuring_service)
    ],
):
    """
    Confirmation professeur qu'une structuration déjà visible en base
    (questions/sections/blocs) est correcte — reprend le pipeline en pause
    à await_structuring_resolution_node. Gap fermé (constaté en test réel) :
    quand AUCUN bloc n'est UNRESOLVED_NO_LABEL, /structure/resolve-blocks
    n'a rien à faire et ne reprend donc jamais le pipeline, laissant
    l'exercice INTERRUPTED sans aucune action professeur possible.
    """
    await structuring_service.confirm_structuring(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
    )


@router.get(
    "/exercises/{exercise_id}/decision-logs",
    response_model=CursorPage[AgentDecisionLogRead],
)
async def get_exercise_agent_decision_logs(
    exercise_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    decision_log_service: Annotated[
        DecisionLogService, Depends(get_decision_log_service)
    ],
    cursor: str | None = None,
    limit: int = 50,
):
    """
    Consultation des logs de décision IA d'un exercice.
    Soumis au contrôle d'accès renforcé (log_security_policy.py §17) :
    - Exercice DRAFT : réservé au professeur créateur uniquement.
    - Exercice publié : professeur créateur ou administrateur uniquement.
    """
    return await decision_log_service.get_exercise_decision_logs(
        exercise_id=exercise_id,
        requesting_user=current_user,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/exercises/{exercise_id}/submissions",
    response_model=CursorPage[SubmissionSummaryRead],
)
async def list_exercise_submissions(
    exercise_id: uuid.UUID,
    current_prof: Annotated[Professor, Depends(get_current_professor)],
    evaluation_service: Annotated[EvaluationService, Depends(get_evaluation_service)],
    cursor: str | None = None,
    limit: int = 50,
):
    """
    Gap trouvé lors de l'audit résultats professeur : SubmissionRepository.
    list_by_exercise existait déjà mais n'était exposé par AUCUN endpoint —
    un professeur n'avait aucun moyen de voir les copies déposées sur un
    de ses exercices sans déjà connaître un submission_id (uniquement via
    contestations/arbitrage, qui ne couvrent que les cas litigieux).
    """
    return await evaluation_service.list_by_exercise_for_professor(
        exercise_id=exercise_id,
        requesting_professor_id=current_prof.id,
        cursor=cursor,
        limit=limit,
    )


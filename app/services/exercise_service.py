"""
Service Exercise — règles métier :
1. create() délègue à ExerciseRepository.create_with_questions() (déjà
   transactionnel) — le service ne fait qu'orchestrer/valider en amont.
2. publish() : seul le PROFESSEUR CRÉATEUR de l'exercice peut le
   publier — vérification d'autorisation explicite.
3. Changement de statut (y compris retour en DRAFT depuis n'importe quel
   état, y compris ARCHIVED_IN_LIBRARY) : AUCUNE restriction — décision
   actée, le professeur garde le contrôle total, pas de protection
   automatique même si des Submission existent déjà.
4. list_by_module() (câblage Recommendation_Agent, Phase 3, navigation de la
   Library) : accessible à tout utilisateur authentifié, même contrôle
   d'accès que get_by_id/list_by_course — ExerciseRead/CriterionRead
   n'exposent aucun détail de correction (verifiable_conditions/test_cases
   restent côté modèle uniquement), rien à restreindre côté lecture.
"""
import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from app.core.exceptions import (
    ExerciseHasSubmissionsError,
    ExerciseNotDraftError,
    ExerciseNotFoundError,
    ExerciseNotPublishedError,
    ForbiddenError,
    IncompleteExerciseSetupError,
    MinimumQuestionCountError,
    MissingDifficultyLevelError,
    NotExerciseOwnerError,
    PublicationNotConfirmedError,
    QuestionNotFoundError,
)
from app.domain.models.assessment.exercise import Exercise, ExerciseDifficulty, ExerciseStatus
from app.domain.models.competency.c2pct_scaffold import get_competency_for_subquestion
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.repositories.pagination import CursorPage
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.module_repository import ModuleRepositoryProtocol
from app.domain.repositories.reasoning_clarification_request_repository import (
    ReasoningClarificationRequestRepositoryProtocol,
)
from app.domain.repositories.solution_variant_repository import SolutionVariantRepositoryProtocol
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.exercise_schemas import (
    CriterionRead,
    ExerciseRead,
    PublicationReadinessQuestionSummary,
    PublicationReadinessRead,
)
from app.infra_services.storage_paths import exercise_reference_document_path, mime_to_extension
from app.infra_services.storage_service import StorageContainer, StorageService
from app.tasks.exercise_tasks import process_exercise_reference_document


class ExerciseServiceProtocol(Protocol):
    async def get_by_id(self, exercise_id: uuid.UUID) -> ExerciseRead: ...
    async def create(
        self,
        module_id: uuid.UUID,
        created_by_professor_id: uuid.UUID,
        title: str,
        description: str | None,
        questions_data: list[dict],
        sections_data: list[dict] | None = None,
    ) -> ExerciseRead: ...
    async def publish(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        status: ExerciseStatus,
        course_id: uuid.UUID | None,
        deadline: datetime | None,
        difficulty_level: ExerciseDifficulty | None = None,
    ) -> ExerciseRead: ...
    async def update_deadline(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        deadline: datetime,
    ) -> ExerciseRead: ...
    async def upload_reference_document(
        self,
        exercise_id: uuid.UUID,
        professor_id: uuid.UUID,
        document_bytes: bytes,
        mime_type: str,
    ) -> ExerciseRead: ...
    async def get_reference_document_url(
        self, exercise_id: uuid.UUID, user_id: uuid.UUID
    ) -> str | None: ...
    async def set_question_bareme(
        self,
        exercise_id: uuid.UUID,
        question_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        points: Decimal,
        criteria: list[dict],
    ) -> ExerciseRead: ...
    async def list_by_course(
        self,
        course_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[ExerciseRead]: ...
    async def list_by_professor(
        self,
        professor_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[ExerciseRead]: ...
    async def list_by_module(
        self,
        module_id: uuid.UUID,
        competency: C2PCTSkillCode | None = None,
        difficulty: ExerciseDifficulty | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[ExerciseRead]: ...
    async def list_assigned_for_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[ExerciseRead]: ...
    async def delete(
        self, exercise_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> None: ...
    async def add_question(
        self, exercise_id: uuid.UUID, requesting_professor_id: uuid.UUID, statement: str
    ) -> ExerciseRead: ...
    async def update_question_statement(
        self,
        exercise_id: uuid.UUID,
        question_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        statement: str,
    ) -> ExerciseRead: ...
    async def delete_question(
        self, exercise_id: uuid.UUID, question_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> ExerciseRead: ...


class ExerciseService:
    def __init__(
        self,
        exercise_repository: ExerciseRepositoryProtocol,
        module_repository: ModuleRepositoryProtocol,
        user_repository: UserRepositoryProtocol,
        clarification_repository: ReasoningClarificationRequestRepositoryProtocol,
        solution_variant_repository: SolutionVariantRepositoryProtocol,
        submission_repository: SubmissionRepositoryProtocol,
        storage_service: StorageService | None = None,
    ) -> None:
        self._exercises = exercise_repository
        self._modules = module_repository
        self._users = user_repository
        self._clarifications = clarification_repository
        self._submissions = submission_repository
        self._variants = solution_variant_repository
        self._storage = storage_service or StorageService()

    async def _to_read(self, exercise: Exercise) -> ExerciseRead:
        """Enrichit et convertit un Exercise en ExerciseRead."""
        module = await self._modules.get_by_id(exercise.module_id)
        professor = await self._users.get_by_id(exercise.created_by_professor_id)
        exercise.module_name = module.name if module else "Unknown"
        exercise.professor_full_name = (
            f"{professor.first_name} {professor.last_name}" if professor else "Unknown"
        )
        return ExerciseRead.model_validate(exercise)

    async def get_by_id(self, exercise_id: uuid.UUID) -> ExerciseRead:
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)
        return await self._to_read(exercise)

    async def create(
        self,
        module_id: uuid.UUID,
        created_by_professor_id: uuid.UUID,
        title: str,
        description: str | None,
        questions_data: list[dict],
        sections_data: list[dict] | None = None,
    ) -> ExerciseRead:
        exercise = await self._exercises.create_with_questions(
            module_id=module_id,
            created_by_professor_id=created_by_professor_id,
            title=title.strip(),
            description=description,
            questions_data=questions_data,
            sections_data=sections_data,
        )
        return await self._to_read(exercise)

    async def publish(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        status: ExerciseStatus,
        course_id: uuid.UUID | None,
        deadline: datetime | None,
        difficulty_level: ExerciseDifficulty | None = None,
    ) -> ExerciseRead:
        raw_exercise = await self._exercises.get_by_id(exercise_id)
        if raw_exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if raw_exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        # Verrou Recommendation_Agent (clôture) — difficulty_level obligatoire
        # UNIQUEMENT au moment de l'archivage en Library (jamais pour
        # DRAFT/EXAM/HOMEWORK, qui n'en ont pas besoin) ; indépendant et
        # cumulatif aux verrous EXAM/HOMEWORK ci-dessous.
        if status == ExerciseStatus.ARCHIVED_IN_LIBRARY and difficulty_level is None:
            raise MissingDifficultyLevelError(exercise_id)

        # Vérification de complétude bloquante — uniquement pour PUBLISHED_AS_EXAM / PUBLISHED_AS_HOMEWORK.
        # Les transitions vers DRAFT ou ARCHIVED_IN_LIBRARY ne sont pas bloquées.
        if status in (ExerciseStatus.PUBLISHED_AS_EXAM, ExerciseStatus.PUBLISHED_AS_HOMEWORK):
            await self._check_completeness(raw_exercise)
            # Confirmation professeur explicite — verrou indépendant et
            # cumulatif à la complétude technique ci-dessus, jamais à sa
            # place. Le hash est recalculé sur l'état ACTUEL (pas celui
            # lu au moment de la confirmation) : toute modification du
            # barème/de la variante de référence depuis la confirmation
            # invalide silencieusement le hash stocké, jamais une simple
            # comparaison de date.
            if raw_exercise.publication_confirmed_hash is None:
                raise PublicationNotConfirmedError(exercise_id, stale=False)
            current_hash = await self._compute_publication_readiness_hash(raw_exercise)
            if raw_exercise.publication_confirmed_hash != current_hash:
                raise PublicationNotConfirmedError(exercise_id, stale=True)

        updated = await self._exercises.publish(
            exercise_id=exercise_id, status=status, course_id=course_id, deadline=deadline,
            difficulty_level=difficulty_level,
        )
        assert updated is not None  # garanti par get_by_id ci-dessus
        return await self._to_read(updated)

    async def update_deadline(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        deadline: datetime,
    ) -> ExerciseRead:
        """
        Report/avance de la date limite d'un examen/devoir DÉJÀ publié —
        gap trouvé (demande explicite professeur) : publish() était le SEUL
        point d'écriture de deadline, mais le rappeler pour ce seul besoin
        forcerait une nouvelle vérification de complétude + confirmation de
        publication (hash), sans rapport avec un simple report de date.
        Jamais pour DRAFT/ARCHIVED_IN_LIBRARY (pas de deadline pertinente
        pour ces statuts) — ExerciseNotPublishedError sinon, même exception
        que le reste du projet pour "exercice non publié".
        """
        raw_exercise = await self._exercises.get_by_id(exercise_id)
        if raw_exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if raw_exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        if raw_exercise.status not in (ExerciseStatus.PUBLISHED_AS_EXAM, ExerciseStatus.PUBLISHED_AS_HOMEWORK):
            raise ExerciseNotPublishedError(exercise_id)

        updated = await self._exercises.update_deadline(exercise_id=exercise_id, deadline=deadline)
        assert updated is not None  # garanti par get_by_id ci-dessus
        return await self._to_read(updated)

    async def confirm_publication_readiness(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
    ) -> PublicationReadinessRead:
        """
        Confirmation professeur explicite (audit "garanties transverses",
        Plan B) — indépendante de publish(), qui exige ensuite cette
        confirmation en plus de la complétude technique. Ne confirme que sur
        un exercice réellement complet : confirmer un état encore incomplet
        n'aurait pas de sens (le résumé serait trompeur).
        """
        raw_exercise = await self._exercises.get_by_id(exercise_id)
        if raw_exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if raw_exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        await self._check_completeness(raw_exercise)

        confirmed_hash = await self._compute_publication_readiness_hash(raw_exercise)
        confirmed_at = datetime.now(timezone.utc)
        updated = await self._exercises.confirm_publication_readiness(
            exercise_id=exercise_id,
            confirmed_hash=confirmed_hash,
            confirmed_at=confirmed_at,
        )
        assert updated is not None  # garanti par get_by_id ci-dessus

        questions_summary = await self._build_publication_readiness_summary(updated)
        return PublicationReadinessRead(
            exercise_id=exercise_id,
            confirmed_at=confirmed_at,
            questions=questions_summary,
        )

    async def _compute_publication_readiness_hash(self, exercise: Exercise) -> str:
        """
        Hash déterministe (sha256) du contenu réellement soumis à
        confirmation — barème + variante de référence par question. Jamais
        une date : capture le CONTENU, pour que toute modification après
        coup (barème changé, nouvelle variante de référence choisie)
        invalide automatiquement une confirmation existante, silencieusement,
        sans mécanisme de détection séparé à maintenir.
        """
        parts: list[str] = []
        for question in sorted(exercise.questions or [], key=lambda q: q.order):
            bareme = question.bareme
            if bareme is not None:
                criteria_key = sorted(
                    (c["id"], c["label"], str(c["points"])) for c in bareme.criteria
                )
                bareme_part = f"{bareme.points}|{criteria_key}"
            else:
                bareme_part = "NONE"

            variants = await self._variants.list_by_question(question.id)
            reference = next((v for v in variants if getattr(v, "is_reference", False)), None)
            variant_part = (
                f"{reference.content}|{reference.structured_content}"
                if reference is not None
                else "NONE"
            )
            parts.append(f"{question.id}:{bareme_part}:{variant_part}")

        canonical = "\n".join(parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def _build_publication_readiness_summary(
        self, exercise: Exercise
    ) -> list[PublicationReadinessQuestionSummary]:
        summaries: list[PublicationReadinessQuestionSummary] = []
        for question in sorted(exercise.questions or [], key=lambda q: q.order):
            bareme = question.bareme
            variants = await self._variants.list_by_question(question.id)
            reference = next((v for v in variants if getattr(v, "is_reference", False)), None)
            # Même bug que _check_completeness (cf. son commentaire) — le
            # total affiché ignorait entièrement le barème C2PCT natif
            # (subquestion_points), affichant 0 pt pour une question
            # pourtant correctement notée par sous-question.
            bareme_points = (
                bareme.points if bareme is not None
                # subquestion_points est stocké en base sous forme de chaînes
                # (cf. ExerciseRepository.set_question_subquestion_points,
                # désérialisation Decimal exacte — jamais un float JSON).
                else sum((Decimal(v) for v in question.subquestion_points.values()), Decimal("0"))
                if question.subquestion_points
                else Decimal("0")
            )
            summaries.append(
                PublicationReadinessQuestionSummary(
                    question_id=question.id,
                    order=question.order,
                    statement=question.statement,
                    bareme_points=bareme_points,
                    bareme_criteria=[
                        CriterionRead(**c) for c in (bareme.criteria if bareme is not None else [])
                    ],
                    reference_variant_summary=(
                        (reference.reasoning_summary or reference.content[:300])
                        if reference is not None
                        else "Aucune variante de référence"
                    ),
                )
            )
        return summaries

    async def _check_completeness(self, exercise: Exercise) -> None:
        """
        Vérifie les 4 conditions bloquantes avant publication.
        Lève IncompleteExerciseSetupError si l'une d'elles n'est pas satisfaite.

        1. Au moins une question définie (gap fermé : la création accepte
           désormais questions=[] — cf. ExerciseCreateRequest, workflow
           upload-only — sans cette garde, un exercice resté à 0 question
           passait trivialement les 3 conditions suivantes, aucune d'elles
           ne s'exécutant jamais sur une liste vide).
        2. Chaque Question doit avoir un Bareme (bareme not None).
        3. Chaque Question doit avoir au moins une SolutionVariant is_reference=True.
        4. Aucune ReasoningClarificationRequest PENDING de sévérité BLOCKING
           liée à cet exercice (Phase 6 : WARNING/INFORMATIONAL — introduites
           par Extraction_Verification_Agent — ne bloquent jamais, seule une
           répartition Cas 2 non confirmée ou une récurrence incomplète le fait).
        """
        questions = exercise.questions or []

        # Condition 1 : au moins une question
        no_questions = len(questions) == 0

        # Condition 2 : barèmes — un barème existe soit via le mécanisme
        # classique (q.bareme), soit via le barème C2PCT natif (Cas 0,
        # q.subquestion_points) : DEUX mécanismes distincts et mutuellement
        # exclusifs pour une même question (cf. docstring QuestionRead.
        # subquestion_points), jamais les deux à la fois. Bug réel corrigé
        # (2026-09-03, test réel examen C2PCT à 3 exercices) : cette
        # condition ne vérifiait QUE q.bareme — un exercice C2PCT natif
        # (bareme TOUJOURS None par conception, cf. _persist_bareme) ne
        # pouvait donc JAMAIS être publié, quelle que soit la qualité réelle
        # de son barème par sous-question.
        missing_baremes = sum(
            1 for q in questions if q.bareme is None and not q.subquestion_points
        )

        # Condition 3 : variantes de référence — une requête par question
        # (pas de eager-loading de solution_variants dans l'agrégat Exercise).
        missing_reference_variants = 0
        for q in questions:
            variants = await self._variants.list_by_question(q.id)
            has_reference = any(getattr(v, "is_reference", False) for v in variants)
            if not has_reference:
                missing_reference_variants += 1

        # Condition 4 : clarifications PENDING de sévérité BLOCKING
        pending_clarifications_list = await self._clarifications.list_pending_blocking_by_exercise(
            exercise.id
        )
        pending_clarifications = len(pending_clarifications_list)

        if no_questions or missing_baremes or missing_reference_variants or pending_clarifications:
            raise IncompleteExerciseSetupError(
                exercise_id=exercise.id,
                no_questions=no_questions,
                missing_baremes=missing_baremes,
                missing_reference_variants=missing_reference_variants,
                pending_clarifications=pending_clarifications,
            )

    async def list_by_course(
        self, course_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[ExerciseRead]:
        page = await self._exercises.list_by_course(course_id, cursor, limit)
        items = [await self._to_read(e) for e in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def list_by_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[ExerciseRead]:
        page = await self._exercises.list_by_professor(professor_id, cursor, limit)
        items = [await self._to_read(e) for e in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def list_by_module(
        self,
        module_id: uuid.UUID,
        competency: C2PCTSkillCode | None = None,
        difficulty: ExerciseDifficulty | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> CursorPage[ExerciseRead]:
        """
        Navigation de la Library (câblage Recommendation_Agent, Phase 3 +
        clôture) — seul appelant réel de list_library_by_module avant ce
        chantier était RecommendationService._build_library_coverage (usage
        interne, jamais exposé). Sans filtre `competency` : pagination
        réelle passthrough, `difficulty` (colonne réelle, cf. docstring
        repository) poussé jusqu'au SQL, comportement inchangé sinon.

        Avec `competency` : la compétence n'est pas une colonne (dérivée de
        Question.covered_subquestions via c2pct_scaffold.
        get_competency_for_subquestion, même principe que _build_library_
        coverage) — un filtre SQL direct est impossible. Choix délibéré pour
        cette première version : parcourt TOUTES les pages en interne et
        renvoie le résultat filtré complet en une seule page (next_cursor
        toujours None) plutôt qu'une pagination réelle sur le sous-ensemble
        filtré — taille attendue modeste de la Library par module, itération
        ultérieure si le besoin de pagination réelle se confirme. `difficulty`
        reste poussé au SQL même dans ce chemin (réduit le nombre de pages à
        parcourir), seul `competency` force le parcours complet.
        """
        if competency is None:
            page = await self._exercises.list_library_by_module(
                module_id, cursor, limit, difficulty_level=difficulty,
            )
            items = [await self._to_read(e) for e in page.items]
            return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

        matching: list[Exercise] = []
        page_cursor: str | None = None
        while True:
            page = await self._exercises.list_library_by_module(
                module_id, page_cursor, limit, difficulty_level=difficulty,
            )
            for exercise in page.items:
                covered = {
                    sub_id
                    for question in exercise.questions
                    for sub_id in (question.covered_subquestions or [])
                }
                if any(get_competency_for_subquestion(sub_id) == competency for sub_id in covered):
                    matching.append(exercise)
            if not page.has_more:
                break
            page_cursor = page.next_cursor

        items = [await self._to_read(e) for e in matching]
        return CursorPage(items=items, next_cursor=None, has_more=False)

    async def list_assigned_for_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[ExerciseRead]:
        """
        Gap fermé (espace étudiant) : ExerciseRepository.
        list_published_exams_for_student existait déjà (examens/devoirs
        publiés dont le Course est rattaché au groupe de l'étudiant) mais
        n'était appelée par AUCUN service ni endpoint — un étudiant n'avait
        aucun moyen de découvrir quels examens/devoirs lui sont assignés
        avant de déposer une copie (seul GET /modules/{id}/library existait,
        portée différente : la bibliothèque d'exercices archivés en
        pratique libre, jamais les examens/devoirs en cours).
        """
        page = await self._exercises.list_published_exams_for_student(student_id, cursor, limit)
        items = [await self._to_read(e) for e in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def upload_reference_document(
        self,
        exercise_id: uuid.UUID,
        professor_id: uuid.UUID,
        document_bytes: bytes,
        mime_type: str,
    ) -> ExerciseRead:
        """
        Dépose le document de référence professeur (énoncé + correction scannés)
        et déclenche le pipeline OCR asynchrone (ExerciseOCRPipelineService).
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != professor_id:
            raise NotExerciseOwnerError(exercise_id, professor_id)

        if exercise.status != ExerciseStatus.DRAFT:
            raise ForbiddenError(
                f"Seul un exercice en DRAFT accepte un document de référence (statut actuel : {exercise.status})"
            )

        if not document_bytes:
            raise ForbiddenError("Le document soumis est vide.")

        extension = mime_to_extension(mime_type)
        blob_path = exercise_reference_document_path(exercise_id, extension)
        await self._storage.upload(
            StorageContainer.EXERCISES,
            blob_path,
            document_bytes,
            content_type=mime_type,
        )

        process_exercise_reference_document.delay(
            exercise_id=str(exercise_id),
            professor_id=str(professor_id),
            document_path=blob_path,
            mime_type=mime_type,
        )

        return await self._to_read(exercise)

    async def get_reference_document_url(self, exercise_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
        """
        Génère une URL SAS pour lire le document de référence.
        On utilise une recherche par préfixe pour trouver l'extension sans multiplier les requêtes.
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)
            
        prefix = f"exercises/{exercise_id}/reference."
        blob_path = await self._storage.find_blob_starting_with(StorageContainer.EXERCISES, prefix)
        
        if blob_path:
            return self._storage.generate_read_url(StorageContainer.EXERCISES, blob_path)
            
        return None

    async def set_question_bareme(
        self,
        exercise_id: uuid.UUID,
        question_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        points: Decimal,
        criteria: list[dict],
    ) -> ExerciseRead:
        """
        Ajout/édition manuelle du barème d'une question APRÈS la création de
        l'exercice — gap trouvé lors de l'audit authoring : create_bareme_
        for_question (Extraction_Verification_Agent) n'était appelable par
        aucun client, et create() n'accepte le barème qu'à la création même
        de l'exercice. Un professeur qui a créé une question sans barème
        (ex. comptant sur l'extraction IA) n'avait alors aucun moyen de
        secours pour en saisir un manuellement.
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        if not any(q.id == question_id for q in exercise.questions or []):
            raise QuestionNotFoundError(question_id)

        updated_bareme = await self._exercises.set_bareme_for_question(
            question_id=question_id, points=points, criteria=criteria,
        )
        assert updated_bareme is not None  # garanti par la vérification d'appartenance ci-dessus

        return await self.get_by_id(exercise_id)

    async def set_question_subquestion_points(
        self,
        exercise_id: uuid.UUID,
        question_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        points: dict[str, Decimal],
    ) -> ExerciseRead:
        """
        Saisie manuelle de secours pour le barème C2PCT natif (Cas 0) —
        même mécanisme que l'extraction automatique (Question.
        subquestion_points), jamais le barème classique. Comble un vrai
        trou : avant cette méthode, set_question_bareme() ci-dessus était
        le seul recours manuel, mais il écrit dans `bareme` (Cas 1/2/3),
        pas `subquestion_points` — un professeur corrigeant ainsi un
        exercice C2PCT natif faisait basculer la question sur le mauvais
        mécanisme de calcul sans le savoir (cf. docstring SubquestionPoints
        Create, exercise_schemas.py). Mêmes verrous d'appartenance que
        set_question_bareme (seul propriétaire, question réellement membre
        de cet exercice).
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        if not any(q.id == question_id for q in exercise.questions or []):
            raise QuestionNotFoundError(question_id)

        await self._exercises.set_question_subquestion_points(
            question_id=question_id, subquestion_points=points,
        )

        return await self.get_by_id(exercise_id)

    async def delete(
        self, exercise_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> None:
        """
        Suppression d'un exercice — gap trouvé lors de l'audit authoring :
        aucun endpoint n'existait pour supprimer un exercice, même un DRAFT
        créé par erreur. Verrous, dans cet ordre :
        1. Propriétaire uniquement (même contrôle que publish()).
        2. DRAFT uniquement — jamais un exercice publié/archivé, même
           redescendu en DRAFT depuis (aucune trace fiable de "jamais publié"
           sinon ; décision volontairement stricte).
        3. Aucune Submission, même sur un DRAFT (ex. attempt orphelin d'un
           ancien statut) — jamais supprimé silencieusement un historique
           d'évaluation étudiant, même partiel.
        Le nettoyage effectif (cascade profonde sur variantes/blocs/étapes
        de raisonnement) est délégué à ExerciseRepository.delete().
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        if exercise.status != ExerciseStatus.DRAFT:
            raise ExerciseNotDraftError(exercise_id, exercise.status)

        submissions_page = await self._submissions.list_by_exercise(exercise_id, limit=1)
        if submissions_page.items:
            raise ExerciseHasSubmissionsError(exercise_id)

        await self._exercises.delete(exercise_id)

    async def _check_owner_and_draft(
        self, exercise_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> Exercise:
        """Garde-fou partagé par add_question/update_question_statement/delete_question."""
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        if exercise.status != ExerciseStatus.DRAFT:
            raise ExerciseNotDraftError(exercise_id, exercise.status)

        return exercise

    async def add_question(
        self, exercise_id: uuid.UUID, requesting_professor_id: uuid.UUID, statement: str
    ) -> ExerciseRead:
        """
        Gap trouvé lors de l'audit CRUD authoring : impossible d'ajouter une
        question à un exercice déjà créé — seule la création initiale
        (ExerciseCreateRequest.questions) ou le pipeline IA (add_structure)
        pouvaient en produire. DRAFT uniquement — jamais sur un exercice déjà
        publié (changerait la structure d'un examen déjà distribué).
        """
        await self._check_owner_and_draft(exercise_id, requesting_professor_id)
        await self._exercises.add_question(exercise_id, statement)
        return await self.get_by_id(exercise_id)

    async def update_question_statement(
        self,
        exercise_id: uuid.UUID,
        question_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        statement: str,
    ) -> ExerciseRead:
        exercise = await self._check_owner_and_draft(exercise_id, requesting_professor_id)

        if not any(q.id == question_id for q in exercise.questions or []):
            raise QuestionNotFoundError(question_id)

        updated = await self._exercises.update_question_statement(question_id, statement)
        assert updated is not None  # garanti par la vérification d'appartenance ci-dessus
        return await self.get_by_id(exercise_id)

    async def delete_question(
        self, exercise_id: uuid.UUID, question_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> ExerciseRead:
        exercise = await self._check_owner_and_draft(exercise_id, requesting_professor_id)

        if not any(q.id == question_id for q in exercise.questions or []):
            raise QuestionNotFoundError(question_id)

        if len(exercise.questions) <= 1:
            raise MinimumQuestionCountError(exercise_id)

        await self._exercises.delete_question(question_id)
        return await self.get_by_id(exercise_id)

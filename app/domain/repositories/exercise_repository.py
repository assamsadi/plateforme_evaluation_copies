"""
Repository Exercise — racine d'agrégat couvrant Exercise + Question +
Bareme (§3 : "un seul formulaire", créés/lus ensemble en une transaction).

QuestionC2PCTSkill a été RETIRÉ de l'agrégat (décision actée) : les 7
compétences C2PCT s'appliquent désormais systématiquement à chaque
question, sans configuration ni pondération par le professeur — plus
rien à charger/créer ici pour les compétences.

Eager loading via selectinload() sur TOUTES les méthodes de lecture qui
retournent l'agrégat complet — évite le problème N+1 (1 requête pour
l'exercice + 1 pour toutes ses questions + 1 pour tous les baremes =
3 requêtes fixes, peu importe le nombre de questions, au lieu d'1 + N + N).
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import delete as sql_delete, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.models.academic.course import Course
from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus
from app.domain.models.assessment.exercise import Exercise, ExerciseDifficulty, ExerciseStatus
from app.domain.models.assessment.exercise_section import ExerciseSection
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepDependency
from app.domain.models.assessment.recommended_exercise import RecommendedExercise
from app.domain.models.assessment.solution_variant import SolutionVariant
from app.domain.models.assessment.teacher_correction_block import TeacherCorrectionBlock
from app.domain.models.identity.user import Student
from app.domain.models.system_infrastructure.job import Job
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)

# Chargement complet de l'agrégat, réutilisé par toutes les méthodes de
# lecture ci-dessous — un seul endroit à maintenir si la structure change.
_AGGREGATE_LOAD_OPTIONS = (
    selectinload(Exercise.sections),
    selectinload(Exercise.questions).selectinload(Question.bareme),
)


class ExerciseRepositoryProtocol(Protocol):
    async def get_by_id(self, exercise_id: uuid.UUID) -> Exercise | None: ...
    async def list_published_exams_for_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]: ...
    async def list_with_expired_deadline(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]: ...
    async def list_library_by_module(
        self,
        module_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        difficulty_level: ExerciseDifficulty | None = None,
    ) -> CursorPage[Exercise]: ...
    async def list_by_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]: ...
    async def list_by_course(
        self, course_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]: ...
    async def create_with_questions(
        self,
        module_id: uuid.UUID,
        created_by_professor_id: uuid.UUID,
        title: str,
        description: str | None,
        questions_data: list[dict],
        sections_data: list[dict] | None = None,
    ) -> Exercise: ...
    async def add_structure(
        self,
        exercise_id: uuid.UUID,
        sections_data: list[dict],
        questions_data: list[dict],
    ) -> tuple[dict[int, uuid.UUID], dict[tuple[int | None, int], uuid.UUID]]: ...
    async def publish(
        self,
        exercise_id: uuid.UUID,
        status: ExerciseStatus,
        course_id: uuid.UUID | None,
        deadline: datetime | None,
        difficulty_level: ExerciseDifficulty | None = None,
    ) -> Exercise | None: ...
    async def confirm_publication_readiness(
        self,
        exercise_id: uuid.UUID,
        confirmed_hash: str,
        confirmed_at: datetime,
    ) -> Exercise | None: ...
    async def update_deadline(self, exercise_id: uuid.UUID, deadline: datetime) -> Exercise | None: ...
    async def create_bareme_for_question(
        self,
        question_id: uuid.UUID,
        points: Decimal,
        criteria: list[dict],
        validation_status: BaremeValidationStatus,
    ) -> Bareme: ...
    async def set_bareme_for_question(
        self,
        question_id: uuid.UUID,
        points: Decimal,
        criteria: list[dict],
    ) -> Bareme | None: ...
    async def set_question_mandated_method(
        self, question_id: uuid.UUID, mandated_method: str | None,
    ) -> None: ...
    async def set_question_covered_subquestions(
        self, question_id: uuid.UUID, covered_subquestions: list[str],
    ) -> None: ...
    async def set_question_subquestion_points(
        self, question_id: uuid.UUID, subquestion_points: dict[str, Decimal] | None,
    ) -> None: ...
    async def set_question_subquestions(
        self, question_id: uuid.UUID, subquestions: list[dict] | None,
    ) -> None: ...
    async def set_question_general_rules(
        self, question_id: uuid.UUID, general_rules: list[str],
    ) -> None: ...
    async def exists_professor_exercise_in_module(
        self, professor_id: uuid.UUID, module_id: uuid.UUID,
    ) -> bool: ...
    async def list_ids_by_module(self, module_id: uuid.UUID) -> list[uuid.UUID]: ...
    async def delete(self, exercise_id: uuid.UUID) -> bool: ...
    async def add_question(
        self, exercise_id: uuid.UUID, statement: str
    ) -> Question | None: ...
    async def update_question_statement(
        self, question_id: uuid.UUID, statement: str
    ) -> Question | None: ...
    async def delete_question(self, question_id: uuid.UUID) -> bool: ...
    async def count_by_status(self) -> dict[str, int]: ...


def _jsonb_safe_criteria(criteria: list[dict]) -> list[dict]:
    """
    Bug corrigé (trouvé en peuplant des données de démo réalistes) :
    CriterionCreate.points est typé Decimal (cf. exercise_schemas.py) — un
    dict issu de .model_dump() porte donc un vrai objet Decimal, que le
    sérialiseur JSON par défaut de la colonne JSONB `Bareme.criteria` ne
    sait pas encoder (TypeError: Object of type Decimal is not JSON
    serializable, plantait l'INSERT à chaque barème avec au moins un
    critère). Jamais détecté avant : les tests unitaires mockent la session,
    aucun ne déclenche un vrai INSERT JSONB avec une valeur Decimal réelle.
    Même conversion str() déjà appliquée côté extraction_verification_
    service.py (agent) — ici alignée pour les deux chemins de saisie
    manuelle (create_with_questions, set_bareme_for_question).
    """
    return [
        {**c, "points": str(c["points"])} if isinstance(c.get("points"), Decimal) else c
        for c in criteria
    ]


class SQLAlchemyExerciseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, exercise_id: uuid.UUID) -> Exercise | None:
        # populate_existing=True : sans ça, un Exercise déjà présent dans
        # l'identity map de la session (ex. juste rendu par create_with_questions
        # ou add_structure, dans la même transaction) garde ses collections
        # sections/questions telles que chargées à ce moment-là — un nouveau
        # SELECT avec selectinload ne les rafraîchit pas tout seul.
        query = (
            select(Exercise)
            .where(Exercise.id == exercise_id)
            .options(*_AGGREGATE_LOAD_OPTIONS)
            .execution_options(populate_existing=True)
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def list_published_exams_for_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]:
        """
        Examens/devoirs actifs (PUBLISHED_AS_EXAM ou PUBLISHED_AS_HOMEWORK)
        dont le Course est rattaché au groupe de l'étudiant — cohérent
        avec is_student_in_course_group() de course_repository.py, mais
        ici on filtre directement une LISTE plutôt qu'un simple booléen.
        """
        query = (
            select(Exercise)
            .join(Course, Exercise.course_id == Course.id)
            .join(Student, Student.group_id == Course.group_id)
            .where(
                Student.id == student_id,
                Exercise.status.in_(
                    [ExerciseStatus.PUBLISHED_AS_EXAM, ExerciseStatus.PUBLISHED_AS_HOMEWORK]
                ),
            )
            .options(*_AGGREGATE_LOAD_OPTIONS)
        )
        return await self._paginated_query(query, cursor, limit)

    async def list_with_expired_deadline(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        query = (
            select(Exercise)
            .where(
                Exercise.status.in_([ExerciseStatus.PUBLISHED_AS_EXAM, ExerciseStatus.PUBLISHED_AS_HOMEWORK]),
                Exercise.deadline < now
            )
            .options(*_AGGREGATE_LOAD_OPTIONS)
        )
        return await self._paginated_query(query, cursor, limit)

    async def list_library_by_module(
        self,
        module_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        difficulty_level: ExerciseDifficulty | None = None,
    ) -> CursorPage[Exercise]:
        """
        difficulty_level (clôture Recommendation_Agent) — filtre SQL réel,
        contrairement à `competency` côté ExerciseService.list_by_module
        (dérivée de covered_subquestions, jamais une colonne) :
        difficulty_level EST une colonne, la pagination reste donc réelle
        même filtrée, jamais le parcours de toutes les pages nécessaire
        pour le filtre par compétence.
        """
        conditions = [
            Exercise.module_id == module_id,
            Exercise.status == ExerciseStatus.ARCHIVED_IN_LIBRARY,
        ]
        if difficulty_level is not None:
            conditions.append(Exercise.difficulty_level == difficulty_level)
        query = select(Exercise).where(*conditions).options(*_AGGREGATE_LOAD_OPTIONS)
        return await self._paginated_query(query, cursor, limit)

    async def list_by_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]:
        query = (
            select(Exercise)
            .where(Exercise.created_by_professor_id == professor_id)
            .options(*_AGGREGATE_LOAD_OPTIONS)
        )
        return await self._paginated_query(query, cursor, limit)

    async def exists_professor_exercise_in_module(
        self, professor_id: uuid.UUID, module_id: uuid.UUID,
    ) -> bool:
        """
        Câblage GET /students/{id}/competency-profile (accès professeur,
        Partie 2/2 C2PCT) — seul proxy réel disponible pour "le professeur
        enseigne ce module" : aucune table d'enseignement M:N n'existe
        (Module n'a aucune colonne d'ownership, cf. son docstring), seule
        Exercise.created_by_professor_id est une ownership déjà établie
        ailleurs (grade_appeal_repository.py, exercise_service.py,
        document_structuring_service.py) — un professeur a accès à un
        module s'il y a créé AU MOINS un exercice, jamais deviné autrement.
        """
        query = (
            select(Exercise.id)
            .where(Exercise.module_id == module_id, Exercise.created_by_professor_id == professor_id)
            .limit(1)
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is not None

    async def list_ids_by_module(self, module_id: uuid.UUID) -> list[uuid.UUID]:
        """
        Câblage écran "Profil de compétence" (résumé du module, vue
        professeur) — tous les exercices d'un module quel que soit leur
        statut (DRAFT compris : un étudiant ne peut évidemment pas y avoir
        soumis, mais le filtrer ici n'apporterait rien, juste un WHERE en
        plus jamais discriminant en pratique). Uniquement les ids : sert de
        borne à un IN (...) côté SubmissionRepository, jamais un
        chargement de l'entité complète pour ça.
        """
        query = select(Exercise.id).where(Exercise.module_id == module_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        """Câblage StatisticsService.get_platform_stats — cf. UserRepository.count_by_role (même contrat, statuts absents complétés côté service)."""
        stmt = select(Exercise.status, func.count()).group_by(Exercise.status)
        result = await self._session.execute(stmt)
        return {status.value: count for status, count in result.all()}

    async def list_by_course(
        self, course_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Exercise]:
        query = (
            select(Exercise)
            .where(Exercise.course_id == course_id)
            .options(*_AGGREGATE_LOAD_OPTIONS)
        )
        return await self._paginated_query(query, cursor, limit)

    async def _paginated_query(self, query, cursor: str | None, limit: int) -> CursorPage[Exercise]:
        query = query.order_by(Exercise.created_at, Exercise.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Exercise.created_at, Exercise.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.unique().scalars().all())  # .unique() requis avec selectinload+limit
        return build_cursor_page(rows, limit, lambda e: (e.created_at, e.id))

    async def create_with_questions(
        self,
        module_id: uuid.UUID,
        created_by_professor_id: uuid.UUID,
        title: str,
        description: str | None,
        questions_data: list[dict],
        sections_data: list[dict] | None = None,
    ) -> Exercise:
        """
        Crée l'agrégat complet en une seule transaction.
        `questions_data` : liste de dicts déjà validés.
        `sections_data` : liste optionnelle de dicts pour les sections (détectées par Document_Structuring_Agent).

        Toujours créé en status=DRAFT — la publication est une action
        séparée (cf. publish()), cohérent avec ExercisePublishRequest.
        """
        exercise = Exercise(
            module_id=module_id,
            created_by_professor_id=created_by_professor_id,
            title=title,
            description=description,
            status=ExerciseStatus.DRAFT,
        )
        self._session.add(exercise)
        await self._session.flush()  # attribue exercise.id, nécessaire pour les FK enfants

        section_map: dict[int, uuid.UUID] = {}
        if sections_data:
            for s_data in sections_data:
                section = ExerciseSection(
                    exercise_id=exercise.id,
                    order=s_data["order"],
                    title=s_data["title"],
                )
                self._session.add(section)
                await self._session.flush()
                section_map[s_data["order"]] = section.id

        for q_data in questions_data:
            sec_id = q_data.get("section_id")
            if sec_id is None and "section_order" in q_data:
                sec_id = section_map.get(q_data["section_order"])

            question = Question(
                exercise_id=exercise.id,
                section_id=sec_id,
                order=q_data["order"],
                statement=q_data["statement"],
                attachment_path=q_data.get("attachment_path"),
            )
            self._session.add(question)
            await self._session.flush()  # attribue question.id

            bareme_data = q_data.get("bareme")
            # Bug corrigé (audit CRUD authoring) : bareme_data était lu sans
            # garde de None — QuestionCreate.bareme est explicitement
            # optionnel ("émerge de l'agent ou saisi par le prof"), donc
            # toute question créée sans barème (cas par défaut du formulaire
            # manuel) faisait planter cette méthode avec un TypeError.
            if bareme_data is not None:
                bareme = Bareme(
                    question_id=question.id,
                    points=bareme_data["points"],
                    criteria=_jsonb_safe_criteria([
                        {"id": str(uuid.uuid4()), **c} for c in bareme_data.get("criteria", [])
                    ]),  # génère l'id serveur, cf. convention documentée dans bareme.py
                )
                self._session.add(bareme)

        await self._session.flush()
        return await self.get_by_id(exercise.id)  # recharge avec eager loading complet

    async def add_structure(
        self,
        exercise_id: uuid.UUID,
        sections_data: list[dict],
        questions_data: list[dict],
    ) -> tuple[dict[int, uuid.UUID], dict[tuple[int | None, int], uuid.UUID]]:
        """
        Ajoute des ExerciseSection et Question à un Exercise DÉJÀ existant
        (créé par le professeur, statut DRAFT) — appelée par
        Document_Structuring_Agent (via document_structuring_service),
        jamais par le flux de création manuelle (create_with_questions).

        Aucun Bareme créé ici : à ce stade du pipeline, le barème n'existe
        pas encore — il est produit par Extraction_Verification_Agent.

        `sections_data`  : dicts {"order": int, "title": str}.
        `questions_data` : dicts {"order": int, "statement": str, "section_order": int | None}.

        Retourne (section_id_by_order, question_id_by_key) où question_id_by_key
        est indexé par (section_order, question_order) — la clé composite utilisée
        par document_structuring_service pour résoudre le question_id réel des
        TeacherCorrectionBlock, plutôt qu'un identifiant fabriqué côté agent.
        """
        section_id_by_order: dict[int, uuid.UUID] = {}
        for s_data in sections_data:
            section = ExerciseSection(
                exercise_id=exercise_id,
                order=s_data["order"],
                title=s_data["title"],
            )
            self._session.add(section)
            await self._session.flush()
            section_id_by_order[s_data["order"]] = section.id

        question_id_by_key: dict[tuple[int | None, int], uuid.UUID] = {}
        for q_data in questions_data:
            section_order = q_data.get("section_order")
            section_id = (
                section_id_by_order.get(section_order) if section_order is not None else None
            )
            question = Question(
                exercise_id=exercise_id,
                section_id=section_id,
                order=q_data["order"],
                statement=q_data["statement"],
            )
            self._session.add(question)
            await self._session.flush()
            question_id_by_key[(section_order, q_data["order"])] = question.id

        return section_id_by_order, question_id_by_key

    async def publish(
        self,
        exercise_id: uuid.UUID,
        status: ExerciseStatus,
        course_id: uuid.UUID | None,
        deadline: datetime | None,
        difficulty_level: ExerciseDifficulty | None = None,
    ) -> Exercise | None:
        exercise = await self._session.get(Exercise, exercise_id)
        if exercise is None:
            return None
        exercise.status = status
        exercise.course_id = course_id
        exercise.deadline = deadline
        # Jamais écrasée par None — un appel publish() qui ne concerne pas
        # l'archivage en Library (EXAM/HOMEWORK/retour DRAFT) ne doit jamais
        # effacer une difficulté déjà déclarée lors d'un archivage précédent.
        if difficulty_level is not None:
            exercise.difficulty_level = difficulty_level
        await self._session.flush()
        return await self.get_by_id(exercise_id)

    async def update_deadline(self, exercise_id: uuid.UUID, deadline: datetime) -> Exercise | None:
        """
        Modification de la deadline SEULE, sans repasser par publish() —
        jamais un ré-appel de publish() ici : il forcerait une nouvelle
        vérification de complétude + confirmation de publication (hash),
        inutile pour un simple report de date sur un exercice déjà publié
        (cf. ExerciseService.update_deadline pour le contrôle de statut).
        status/course_id/difficulty_level jamais touchés.
        """
        exercise = await self._session.get(Exercise, exercise_id)
        if exercise is None:
            return None
        exercise.deadline = deadline
        await self._session.flush()
        return await self.get_by_id(exercise_id)

    async def confirm_publication_readiness(
        self,
        exercise_id: uuid.UUID,
        confirmed_hash: str,
        confirmed_at: datetime,
    ) -> Exercise | None:
        exercise = await self._session.get(Exercise, exercise_id)
        if exercise is None:
            return None
        exercise.publication_confirmed_hash = confirmed_hash
        exercise.publication_confirmed_at = confirmed_at
        await self._session.flush()
        return await self.get_by_id(exercise_id)

    async def create_bareme_for_question(
        self,
        question_id: uuid.UUID,
        points: Decimal,
        criteria: list[dict],
        validation_status: BaremeValidationStatus,
    ) -> Bareme:
        """
        Extraction_Verification_Agent (Phase 6) — un seul Bareme par
        Question (contrainte unique), à la différence de create_with_questions
        où le prof saisit son barème en amont : ici la question existe déjà
        (créée par Document_Structuring_Agent), le barème arrive après.
        Chaque critère doit déjà porter son "id" (généré par l'agent, cf.
        BaremeCriterionProposal.id) — jamais régénéré ici, contrairement à
        create_with_questions (saisie manuelle, aucun id encore attribué).
        """
        bareme = Bareme(
            question_id=question_id,
            points=points,
            criteria=criteria,
            validation_status=validation_status,
        )
        self._session.add(bareme)
        await self._session.flush()
        return bareme

    async def set_bareme_for_question(
        self,
        question_id: uuid.UUID,
        points: Decimal,
        criteria: list[dict],
    ) -> Bareme | None:
        """
        Upsert manuel (édition professeur après coup, hors pipeline agent) :
        crée le Bareme s'il n'existe pas encore, sinon remplace points/
        criteria en place — jamais un second Bareme (contrainte unique sur
        question_id, cf. create_bareme_for_question). Toujours CONFIRMED
        (saisie professeur directe, jamais PENDING_REVIEW comme Cas 2 agent).

        Bug corrigé (test réel, 2026-08-31) : CriterionCreate (schéma de ce
        formulaire manuel) ne porte QUE label/points — jamais correction_mode
        ni les autres champs enrichis (verifiable_conditions, rubric_levels,
        expected_steps, test_cases, reference_code, expected_complexity).
        Remplacer bareme.criteria EN PLACE sans égard pour ces champs
        écrasait silencieusement un barème automatique déjà correct et
        COMPLET (Extraction_Verification_Agent, _persist_bareme) dès qu'un
        professeur rouvrait ne serait-ce qu'UNE fois ce formulaire —
        constaté concrètement : un barème avec correction_mode="binary_
        checklist" correctement déterminé par l'agent, perdu après un
        passage par ce endpoint, causant un KeyError('correction_mode') en
        aval (comparative_evaluation_node.py) au moment de la notation.
        Correctif : les champs enrichis d'un critère existant (même label)
        sont conservés si le nouveau payload manuel ne les fournit pas —
        jamais perdus par une simple réédition de points/label. Un critère
        VRAIMENT nouveau (aucun match par label) reçoit CRITERIA_BASED par
        défaut (cf. CorrectionMode, "tout cas ambigu est classé
        CRITERIA_BASED") plutôt qu'un champ absent qui replante plus tard.
        """
        question = await self._session.get(Question, question_id)
        if question is None:
            return None

        result = await self._session.execute(
            select(Bareme).where(Bareme.question_id == question_id)
        )
        bareme = result.scalar_one_or_none()

        _ENRICHED_FIELDS = (
            "correction_mode", "verifiable_conditions", "rubric_levels",
            "expected_steps", "test_cases", "reference_code", "expected_complexity",
        )
        old_by_label = {c["label"]: c for c in (bareme.criteria if bareme else [])}

        def _merge_with_existing(new_criterion: dict) -> dict:
            old = old_by_label.get(new_criterion["label"])
            merged = dict(new_criterion)
            for field in _ENRICHED_FIELDS:
                if field not in merged and old is not None and field in old:
                    merged[field] = old[field]
            merged.setdefault("correction_mode", "criteria_based")
            return merged

        criteria_with_ids = _jsonb_safe_criteria(
            [_merge_with_existing({"id": str(uuid.uuid4()), **c}) for c in criteria]
        )

        if bareme is None:
            bareme = Bareme(
                question_id=question_id,
                points=points,
                criteria=criteria_with_ids,
                validation_status=BaremeValidationStatus.CONFIRMED,
            )
            self._session.add(bareme)
        else:
            bareme.points = points
            bareme.criteria = criteria_with_ids
            bareme.validation_status = BaremeValidationStatus.CONFIRMED

        await self._session.flush()
        return bareme

    async def set_question_mandated_method(
        self, question_id: uuid.UUID, mandated_method: str | None,
    ) -> None:
        question = await self._session.get(Question, question_id)
        if question is None:
            return
        question.mandated_method = mandated_method
        await self._session.flush()

    async def set_question_covered_subquestions(
        self, question_id: uuid.UUID, covered_subquestions: list[str],
    ) -> None:
        question = await self._session.get(Question, question_id)
        if question is None:
            return
        question.covered_subquestions = covered_subquestions
        await self._session.flush()

    async def set_question_subquestion_points(
        self, question_id: uuid.UUID, subquestion_points: dict[str, Decimal] | None,
    ) -> None:
        """
        Chantier barème C2PCT natif (Cas 0) — sérialisé en texte (jamais un
        float JSON) pour une désérialisation Decimal exacte côté lecture,
        même discipline que Bareme.criteria (cf. _persist_bareme,
        extraction_verification_service.py).
        """
        question = await self._session.get(Question, question_id)
        if question is None:
            return
        question.subquestion_points = (
            {sq_id: str(points) for sq_id, points in subquestion_points.items()}
            if subquestion_points else None
        )
        await self._session.flush()

    async def set_question_subquestions(
        self, question_id: uuid.UUID, subquestions: list[dict] | None,
    ) -> None:
        """
        2026-08-29 (backlog_bugs_c2pct.md) — extraits verbatim déjà vérifiés
        déterministiquement côté agent (cf. Extraction_Verification_Agent.
        _find_verbatim_span) ; ce repository ne fait que persister tel quel,
        aucune revérification ici.
        """
        question = await self._session.get(Question, question_id)
        if question is None:
            return
        question.subquestions = subquestions
        await self._session.flush()

    async def set_question_general_rules(
        self, question_id: uuid.UUID, general_rules: list[str],
    ) -> None:
        question = await self._session.get(Question, question_id)
        if question is None:
            return
        question.general_rules = general_rules
        await self._session.flush()

    async def delete(self, exercise_id: uuid.UUID) -> bool:
        """
        Suppression complète d'un exercice — cascade MANUELLE en profondeur,
        contrairement à ce qu'on pourrait attendre de session.delete(exercise)
        seul : Exercise.questions et Question.bareme portent bien cascade=
        "all, delete-orphan" (cf. modèles), donc Question et Bareme seraient
        déjà correctement supprimés en cascade ORM — mais SolutionVariant,
        TeacherCorrectionBlock, ReasoningStep, ReasoningStepDependency,
        ReasoningClarificationRequest, Job et RecommendedExercise n'ont
        AUCUNE relation ORM déclarée vers Exercise/Question (simples FK
        "lâches", jamais mappées en relationship()) ni de ondelete=CASCADE
        en base (vérifié directement via information_schema : seule
        exercise_sections a CASCADE, toutes les autres FK vers exercises
        sont en NO ACTION) : sans ce nettoyage explicite, la suppression
        échoue sur une violation de contrainte FK dès la première ligne
        rencontrée dans l'une de ces tables. Ordre strict feuille -> racine.

        Bug constaté en test réel (dépôt d'un document de référence, upload
        Azure réussi, pipeline OCR/structuration ayant tourné au moins une
        fois) : un Job est TOUJOURS créé pour l'exercice dès qu'un document
        est déposé — jamais nettoyé ici avant ce correctif — donc toute
        tentative de suppression d'un exercice ayant déjà reçu un dépôt
        échouait systématiquement (IntegrityError non gérée -> 500), alors
        même que le garde-fou DRAFT+aucune Submission était respecté.

        Le garde-fou métier (DRAFT uniquement, aucune Submission) est
        appliqué en amont par ExerciseService.delete() — ce repository ne
        fait qu'exécuter la suppression déjà autorisée.
        """
        exercise = await self.get_by_id(exercise_id)
        if exercise is None:
            return False

        question_ids = [q.id for q in exercise.questions]
        await self._delete_variants_and_clarifications_for_questions(question_ids)

        await self._session.execute(
            sql_delete(TeacherCorrectionBlock).where(TeacherCorrectionBlock.exercise_id == exercise_id)
        )
        await self._session.execute(
            sql_delete(Job).where(Job.exercise_id == exercise_id)
        )
        await self._session.execute(
            sql_delete(RecommendedExercise).where(RecommendedExercise.exercise_id == exercise_id)
        )

        # Cascade ORM à partir d'ici : Question (cascade="all, delete-orphan")
        # -> Bareme (idem) ; ExerciseSection via ondelete="CASCADE" en base.
        await self._session.delete(exercise)
        await self._session.flush()
        return True

    async def _delete_variants_and_clarifications_for_questions(
        self, question_ids: list[uuid.UUID]
    ) -> None:
        """
        Nettoyage feuille -> racine partagé par delete() (toutes les
        questions d'un exercice) et delete_question() (une seule) :
        SolutionVariant, ReasoningStep, ReasoningStepDependency et
        ReasoningClarificationRequest n'ont AUCUNE relation ORM déclarée vers
        Question ni de ondelete=CASCADE en base (simples FK "lâches") — sans
        ce nettoyage explicite, la suppression échouerait sur une violation
        de contrainte FK dès la première SolutionVariant rencontrée.
        """
        if not question_ids:
            return

        variant_ids_result = await self._session.execute(
            select(SolutionVariant.id).where(SolutionVariant.question_id.in_(question_ids))
        )
        variant_ids = [row[0] for row in variant_ids_result.all()]

        if variant_ids:
            step_ids_result = await self._session.execute(
                select(ReasoningStep.id).where(ReasoningStep.variant_id.in_(variant_ids))
            )
            step_ids = [row[0] for row in step_ids_result.all()]

            if step_ids:
                await self._session.execute(
                    sql_delete(ReasoningStepDependency).where(
                        or_(
                            ReasoningStepDependency.step_id.in_(step_ids),
                            ReasoningStepDependency.depends_on_step_id.in_(step_ids),
                        )
                    )
                )
                await self._session.execute(
                    sql_delete(ReasoningStep).where(ReasoningStep.id.in_(step_ids))
                )

            await self._session.execute(
                sql_delete(ReasoningClarificationRequest).where(
                    ReasoningClarificationRequest.variant_id.in_(variant_ids)
                )
            )
            await self._session.execute(
                sql_delete(SolutionVariant).where(SolutionVariant.id.in_(variant_ids))
            )

        # Clarifications référençant directement une Question sans passer par
        # une variante (Phase 6, related_entity_id — pas une vraie FK, ne
        # bloquerait pas la suppression, mais laisserait des lignes
        # orphelines évitables).
        await self._session.execute(
            sql_delete(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_type == "Question",
                ReasoningClarificationRequest.related_entity_id.in_(question_ids),
            )
        )

    async def add_question(
        self, exercise_id: uuid.UUID, statement: str
    ) -> Question | None:
        """
        Ajoute une Question à un Exercise existant, sans Bareme (saisi
        séparément via set_bareme_for_question, même flux que la correction
        d'un barème existant) — order auto-calculé (max existant + 1, ou 1
        si aucune question).
        """
        exercise = await self.get_by_id(exercise_id)
        if exercise is None:
            return None

        next_order = max((q.order for q in exercise.questions), default=0) + 1
        question = Question(
            exercise_id=exercise_id,
            order=next_order,
            statement=statement,
        )
        self._session.add(question)
        await self._session.flush()
        return question

    async def update_question_statement(
        self, question_id: uuid.UUID, statement: str
    ) -> Question | None:
        question = await self._session.get(Question, question_id)
        if question is None:
            return None
        question.statement = statement
        await self._session.flush()
        return question

    async def delete_question(self, question_id: uuid.UUID) -> bool:
        """
        Supprime une Question isolément (contrairement à delete(), qui
        supprime l'exercice entier) — même cascade manuelle sur ses propres
        SolutionVariant/ReasoningStep/ReasoningClarificationRequest, plus les
        TeacherCorrectionBlock qui lui sont rattachés (question_id nullable,
        jamais tous les blocs de l'exercice : ceux liés à d'autres questions
        ou encore UNRESOLVED_NO_LABEL ne doivent pas disparaître).
        """
        question = await self._session.get(Question, question_id)
        if question is None:
            return False

        await self._delete_variants_and_clarifications_for_questions([question_id])

        await self._session.execute(
            sql_delete(TeacherCorrectionBlock).where(TeacherCorrectionBlock.question_id == question_id)
        )

        # Cascade ORM : Bareme (cascade="all, delete-orphan" sur Question.bareme).
        await self._session.delete(question)
        await self._session.flush()
        return True
"""
Tests du ExerciseRepository — couvre toutes les méthodes publiques :
- create_with_questions (nominal, vérifie eager loading questions+bareme)
- get_by_id (nominal avec relations chargées, non trouvé)
- publish (nominal, non trouvé)
- list_by_professor (nominal, filtre, pagination)
- list_by_course (nominal, filtre)
- list_library_by_module (nominal, filtre par statut ARCHIVED)
- list_published_exams_for_student (nominal, filtre par groupe étudiant)
- list_with_expired_deadline (nominal, filtre par deadline expirée)
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.models.academic.course import Course
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.identity.user import Student, Professor, UserRole, AcademicStatus
from app.domain.repositories.course_repository import SQLAlchemyCourseRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository


@pytest.fixture
async def program(db_session):
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Test Program {uuid.uuid4().hex[:8]}", code=f"TP{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def module(db_session, program):
    repo = SQLAlchemyModuleRepository(db_session)
    return await repo.create(program_id=program.id, name=f"Test Module {uuid.uuid4().hex[:8]}", code=f"TM{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def group(db_session, program):
    repo = SQLAlchemyGroupRepository(db_session)
    return await repo.create(program_id=program.id, label=f"G{uuid.uuid4().hex[:6]}", academic_year="2025-2026")


@pytest.fixture
async def professor(db_session):
    prof = Professor(
        id=uuid.uuid4(),
        role=UserRole.PROFESSOR,
        first_name="Bob",
        last_name="Martin",
        email=f"prof_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        department="Informatique",
        title="Dr",
        employee_number=f"EMP{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prof)
    await db_session.flush()
    return prof


@pytest.fixture
async def other_professor(db_session):
    prof = Professor(
        id=uuid.uuid4(),
        role=UserRole.PROFESSOR,
        first_name="Alice",
        last_name="Smith",
        email=f"prof2_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        department="Math",
        title="Pr",
        employee_number=f"EMP{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prof)
    await db_session.flush()
    return prof


@pytest.fixture
async def student(db_session, group):
    s = Student(
        id=uuid.uuid4(),
        role=UserRole.STUDENT,
        first_name="Charlie",
        last_name="Dupont",
        email=f"student_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        student_number=f"STU{uuid.uuid4().hex[:6]}",
        group_id=group.id,
        enrollment_year=2025,
        academic_status=AcademicStatus.ACTIVE,
        level="L3",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
async def course(db_session, module, professor, group):
    repo = SQLAlchemyCourseRepository(db_session)
    return await repo.create(
        module_id=module.id,
        professor_user_id=professor.id,
        group_id=group.id,
        semester="S1-2025",
    )


@pytest.fixture
def questions_data():
    """Données de questions pour create_with_questions, au format attendu."""
    return [
        {
            "order": 1,
            "statement": "Calculer l'aire du triangle.",
            "attachment_path": None,
            "bareme": {
                "points": Decimal("5.00"),
                "criteria": [
                    {"label": "Formule correcte", "points": 2.0},
                    {"label": "Calcul correct", "points": 3.0},
                ],
            },
        },
        {
            "order": 2,
            "statement": "Démontrer le théorème de Pythagore.",
            "bareme": {
                "points": Decimal("10.00"),
                "criteria": [
                    {"label": "Hypothèses", "points": 3.0},
                    {"label": "Raisonnement", "points": 7.0},
                ],
            },
        },
    ]


@pytest.mark.anyio
class TestExerciseRepositoryCreateWithQuestions:
    """Tests de la méthode create_with_questions()."""

    async def test_create_nominal(self, db_session, module, professor, questions_data):
        repo = SQLAlchemyExerciseRepository(db_session)
        exercise = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Examen Final",
            description="Description test",
            questions_data=questions_data,
        )

        assert exercise.id is not None
        assert exercise.module_id == module.id
        assert exercise.created_by_professor_id == professor.id
        assert exercise.title == "Examen Final"
        assert exercise.description == "Description test"
        assert exercise.status == ExerciseStatus.DRAFT

    async def test_create_eager_loads_questions_and_bareme(self, db_session, module, professor, questions_data):
        """Vérifie que get_by_id charge eagerly les questions et leurs baremes (selectinload)."""
        repo = SQLAlchemyExerciseRepository(db_session)
        created = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Test Eager",
            description=None,
            questions_data=questions_data,
        )

        found = await repo.get_by_id(created.id)

        assert found is not None
        assert len(found.questions) == 2
        assert found.questions[0].order == 1
        assert found.questions[0].statement == "Calculer l'aire du triangle."
        assert found.questions[0].bareme is not None
        assert found.questions[0].bareme.points == Decimal("5.00")
        assert len(found.questions[0].bareme.criteria) == 2
        assert found.questions[1].order == 2
        assert found.questions[1].bareme.points == Decimal("10.00")

    async def test_create_with_question_without_bareme(self, db_session, module, professor):
        """
        Bug corrigé (audit CRUD authoring) : une question sans barème
        (QuestionCreate.bareme=None, cas par défaut du formulaire manuel de
        création d'exercice) faisait planter create_with_questions avec un
        TypeError ("'NoneType' object is not subscriptable") — bareme_data
        était lu sans garde de None. Jamais couvert avant : le seul test
        avec bareme=None passait par add_structure() (pipeline IA), un
        chemin de code entièrement différent qui ne crée jamais de Bareme.
        """
        repo = SQLAlchemyExerciseRepository(db_session)
        created = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Exercice sans barème",
            description=None,
            questions_data=[
                {"order": 1, "statement": "Question sans barème.", "bareme": None},
            ],
        )

        found = await repo.get_by_id(created.id)

        assert len(found.questions) == 1
        assert found.questions[0].bareme is None

    async def test_create_questions_ordered_correctly(self, db_session, module, professor, questions_data):
        """Vérifie que les questions sont triées par order (relationship order_by)."""
        repo = SQLAlchemyExerciseRepository(db_session)
        created = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Order Test",
            description=None,
            questions_data=questions_data,
        )

        found = await repo.get_by_id(created.id)

        assert found.questions[0].order < found.questions[1].order

    async def test_create_with_decimal_criteria_points(self, db_session, module, professor):
        """
        Bug corrigé (trouvé en peuplant des données de démo réalistes) :
        un critère de barème dont `points` est un vrai Decimal (ce que
        produit systématiquement CriterionCreate.model_dump() en
        production — cf. exercise_schemas.py, jamais un float comme le
        fixture `questions_data` ci-dessus qui masquait le bug) faisait
        planter l'INSERT avec TypeError("Object of type Decimal is not
        JSON serializable") — la colonne JSONB `criteria` ne peut pas
        encoder un Decimal directement. Jamais détecté avant : aucun test
        existant n'utilisait un vrai Decimal ici, uniquement des float.
        """
        repo = SQLAlchemyExerciseRepository(db_session)
        created = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Barème avec Decimal réel",
            description=None,
            questions_data=[
                {
                    "order": 1,
                    "statement": "Question avec critères Decimal.",
                    "bareme": {
                        "points": Decimal("8.00"),
                        "criteria": [
                            {"label": "Critère 1", "points": Decimal("4")},
                            {"label": "Critère 2", "points": Decimal("4")},
                        ],
                    },
                },
            ],
        )

        found = await repo.get_by_id(created.id)

        assert found.questions[0].bareme is not None
        criteria = found.questions[0].bareme.criteria
        assert len(criteria) == 2
        assert criteria[0]["points"] == "4"
        assert criteria[1]["points"] == "4"


@pytest.mark.anyio
class TestExerciseRepositorySetBaremeForQuestion:
    """
    set_bareme_for_question() — édition manuelle du barème après création
    (PUT /exercises/{id}/questions/{id}/bareme). Même bug Decimal->JSONB
    que create_with_questions (cf. TestExerciseRepositoryCreateWithQuestions.
    test_create_with_decimal_criteria_points), corrigé par le même helper
    partagé _jsonb_safe_criteria.
    """

    async def test_set_bareme_with_decimal_criteria_points(self, db_session, module, professor):
        repo = SQLAlchemyExerciseRepository(db_session)
        created = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Exercice à éditer",
            description=None,
            questions_data=[{"order": 1, "statement": "Question sans barème.", "bareme": None}],
        )
        question_id = created.questions[0].id

        bareme = await repo.set_bareme_for_question(
            question_id=question_id,
            points=Decimal("6.00"),
            criteria=[
                {"label": "Exactitude", "points": Decimal("3")},
                {"label": "Justification", "points": Decimal("3")},
            ],
        )

        assert bareme is not None
        assert len(bareme.criteria) == 2
        assert bareme.criteria[0]["points"] == "3"
        assert bareme.criteria[1]["points"] == "3"


@pytest.mark.anyio
class TestExerciseRepositoryAddStructure:
    """Tests de add_structure() — utilisée par Document_Structuring_Agent
    (via document_structuring_service) pour ajouter sections/questions à
    un Exercise déjà existant, sans Bareme."""

    async def test_add_structure_creates_sections_and_questions(self, db_session, module, professor):
        repo = SQLAlchemyExerciseRepository(db_session)
        exercise = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Sujet déposé",
            description=None,
            questions_data=[],
        )

        sections_data = [{"order": 1, "title": "Exercice 1"}]
        questions_data = [
            {"order": 1, "statement": "Calculer l'aire", "section_order": 1},
            {"order": 2, "statement": "Calculer le volume", "section_order": 1},
        ]

        section_id_by_order, question_id_by_key = await repo.add_structure(
            exercise_id=exercise.id,
            sections_data=sections_data,
            questions_data=questions_data,
        )

        assert set(section_id_by_order.keys()) == {1}
        assert set(question_id_by_key.keys()) == {(1, 1), (1, 2)}

        found = await repo.get_by_id(exercise.id)
        assert len(found.questions) == 2
        assert found.questions[0].bareme is None
        assert found.questions[0].section_id == section_id_by_order[1]

    async def test_add_structure_question_without_section(self, db_session, module, professor):
        repo = SQLAlchemyExerciseRepository(db_session)
        exercise = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Sujet sans section",
            description=None,
            questions_data=[],
        )

        question_id_by_key_result = await repo.add_structure(
            exercise_id=exercise.id,
            sections_data=[],
            questions_data=[{"order": 1, "statement": "Question unique", "section_order": None}],
        )
        _, question_id_by_key = question_id_by_key_result

        assert (None, 1) in question_id_by_key

        found = await repo.get_by_id(exercise.id)
        assert found.questions[0].section_id is None


@pytest.mark.anyio
class TestExerciseRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_not_found_returns_none(self, db_session):
        repo = SQLAlchemyExerciseRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestExerciseRepositoryPublish:
    """Tests de la méthode publish()."""

    async def test_publish_as_exam(self, db_session, module, professor, course, questions_data):
        repo = SQLAlchemyExerciseRepository(db_session)
        exercise = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="To Publish",
            description=None,
            questions_data=questions_data,
        )
        assert exercise.status == ExerciseStatus.DRAFT

        deadline = datetime.now(timezone.utc) + timedelta(days=7)
        published = await repo.publish(
            exercise_id=exercise.id,
            status=ExerciseStatus.PUBLISHED_AS_EXAM,
            course_id=course.id,
            deadline=deadline,
        )

        assert published is not None
        assert published.status == ExerciseStatus.PUBLISHED_AS_EXAM
        assert published.course_id == course.id
        assert published.deadline == deadline

    async def test_publish_as_library(self, db_session, module, professor, questions_data):
        repo = SQLAlchemyExerciseRepository(db_session)
        exercise = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="Library",
            description=None,
            questions_data=questions_data,
        )

        published = await repo.publish(
            exercise_id=exercise.id,
            status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
            course_id=None,
            deadline=None,
        )

        assert published is not None
        assert published.status == ExerciseStatus.ARCHIVED_IN_LIBRARY
        assert published.course_id is None
        assert published.deadline is None

    async def test_publish_not_found_returns_none(self, db_session):
        repo = SQLAlchemyExerciseRepository(db_session)

        result = await repo.publish(
            exercise_id=uuid.uuid4(),
            status=ExerciseStatus.PUBLISHED_AS_EXAM,
            course_id=None,
            deadline=None,
        )

        assert result is None


@pytest.mark.anyio
class TestExerciseRepositoryConfirmPublicationReadiness:
    """Tests de confirm_publication_readiness() (audit "garanties transverses", Plan B)."""

    async def test_confirm_publication_readiness_persists_hash_and_timestamp(
        self, db_session, module, professor, questions_data
    ):
        repo = SQLAlchemyExerciseRepository(db_session)
        exercise = await repo.create_with_questions(
            module_id=module.id,
            created_by_professor_id=professor.id,
            title="To Confirm",
            description=None,
            questions_data=questions_data,
        )
        assert exercise.publication_confirmed_hash is None
        assert exercise.publication_confirmed_at is None

        confirmed_at = datetime.now(timezone.utc)
        updated = await repo.confirm_publication_readiness(
            exercise_id=exercise.id,
            confirmed_hash="deadbeef" * 8,
            confirmed_at=confirmed_at,
        )

        assert updated is not None
        assert updated.publication_confirmed_hash == "deadbeef" * 8
        assert updated.publication_confirmed_at is not None

    async def test_confirm_publication_readiness_not_found_returns_none(self, db_session):
        repo = SQLAlchemyExerciseRepository(db_session)

        result = await repo.confirm_publication_readiness(
            exercise_id=uuid.uuid4(),
            confirmed_hash="x",
            confirmed_at=datetime.now(timezone.utc),
        )

        assert result is None


@pytest.mark.anyio
class TestExerciseRepositoryListByProfessor:
    """Tests de la méthode list_by_professor()."""

    async def test_list_by_professor_nominal(self, db_session, module, professor, other_professor, questions_data):
        repo = SQLAlchemyExerciseRepository(db_session)
        e1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Ex1", description=None, questions_data=questions_data,
        )
        e2 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=other_professor.id,
            title="Ex2", description=None, questions_data=questions_data,
        )

        page = await repo.list_by_professor(professor.id)

        assert len(page.items) == 1
        assert page.items[0].id == e1.id
        assert page.items[0].created_by_professor_id == professor.id

    async def test_list_by_professor_empty(self, db_session, professor):
        repo = SQLAlchemyExerciseRepository(db_session)

        page = await repo.list_by_professor(professor.id)

        assert page.items == []
        assert page.has_more is False

    async def test_list_by_professor_pagination(self, db_session, module, professor, questions_data):
        repo = SQLAlchemyExerciseRepository(db_session)
        for i in range(5):
            await repo.create_with_questions(
                module_id=module.id, created_by_professor_id=professor.id,
                title=f"Ex {i}", description=None, questions_data=questions_data,
            )

        first_page = await repo.list_by_professor(professor.id, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_by_professor(professor.id, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id


@pytest.mark.anyio
class TestExerciseRepositoryListByCourse:
    """Tests de la méthode list_by_course()."""

    async def test_list_by_course_nominal(self, db_session, module, professor, course, questions_data):
        repo = SQLAlchemyExerciseRepository(db_session)
        e1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Ex1", description=None, questions_data=questions_data,
        )
        await repo.publish(e1.id, ExerciseStatus.PUBLISHED_AS_EXAM, course.id, None)

        page = await repo.list_by_course(course.id)

        assert len(page.items) == 1
        assert page.items[0].id == e1.id
        assert page.items[0].course_id == course.id

    async def test_list_by_course_empty(self, db_session, course):
        repo = SQLAlchemyExerciseRepository(db_session)

        page = await repo.list_by_course(course.id)

        assert page.items == []


@pytest.mark.anyio
class TestExerciseRepositoryListLibraryByModule:
    """Tests de la méthode list_library_by_module()."""

    async def test_list_library_nominal(self, db_session, module, professor, questions_data):
        repo = SQLAlchemyExerciseRepository(db_session)
        e1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Lib1", description=None, questions_data=questions_data,
        )
        await repo.publish(e1.id, ExerciseStatus.ARCHIVED_IN_LIBRARY, None, None)

        e2 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Draft2", description=None, questions_data=questions_data,
        )
        # e2 reste DRAFT, ne doit pas apparaître

        page = await repo.list_library_by_module(module.id)

        assert len(page.items) == 1
        assert page.items[0].id == e1.id
        assert page.items[0].status == ExerciseStatus.ARCHIVED_IN_LIBRARY

    async def test_list_library_empty(self, db_session, module):
        repo = SQLAlchemyExerciseRepository(db_session)

        page = await repo.list_library_by_module(module.id)

        assert page.items == []

    async def test_list_library_filters_by_difficulty_level(self, db_session, module, professor, questions_data):
        """Clôture — difficulty_level EST une colonne réelle : filtre SQL direct, jamais un parcours applicatif."""
        from app.domain.models.assessment.exercise import ExerciseDifficulty

        repo = SQLAlchemyExerciseRepository(db_session)
        facile = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Facile", description=None, questions_data=questions_data,
        )
        await repo.publish(facile.id, ExerciseStatus.ARCHIVED_IN_LIBRARY, None, None, ExerciseDifficulty.FACILE)

        avance = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Avance", description=None, questions_data=questions_data,
        )
        await repo.publish(avance.id, ExerciseStatus.ARCHIVED_IN_LIBRARY, None, None, ExerciseDifficulty.AVANCE)

        page = await repo.list_library_by_module(module.id, difficulty_level=ExerciseDifficulty.FACILE)

        assert len(page.items) == 1
        assert page.items[0].id == facile.id


@pytest.mark.anyio
class TestExerciseRepositoryListPublishedExamsForStudent:
    """Tests de la méthode list_published_exams_for_student()."""

    async def test_list_published_exams_for_student_nominal(
        self, db_session, module, professor, course, student, questions_data
    ):
        """L'étudiant voit les examens publiés pour son groupe."""
        repo = SQLAlchemyExerciseRepository(db_session)
        e1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Exam", description=None, questions_data=questions_data,
        )
        await repo.publish(e1.id, ExerciseStatus.PUBLISHED_AS_EXAM, course.id, None)

        page = await repo.list_published_exams_for_student(student.id)

        assert len(page.items) == 1
        assert page.items[0].id == e1.id
        assert page.items[0].status == ExerciseStatus.PUBLISHED_AS_EXAM

    async def test_list_published_exams_excludes_draft(self, db_session, module, professor, course, student, questions_data):
        """Les exercices DRAFT ne sont pas visibles par l'étudiant."""
        repo = SQLAlchemyExerciseRepository(db_session)
        await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Draft", description=None, questions_data=questions_data,
        )

        page = await repo.list_published_exams_for_student(student.id)

        assert page.items == []

    async def test_list_published_exams_excludes_library(self, db_session, module, professor, course, student, questions_data):
        """Les exercices ARCHIVED_IN_LIBRARY ne sont pas dans les examens publiés."""
        repo = SQLAlchemyExerciseRepository(db_session)
        e1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Lib", description=None, questions_data=questions_data,
        )
        await repo.publish(e1.id, ExerciseStatus.ARCHIVED_IN_LIBRARY, None, None)

        page = await repo.list_published_exams_for_student(student.id)

        assert page.items == []


@pytest.mark.anyio
class TestExerciseRepositoryListWithExpiredDeadline:
    """Tests de la méthode list_with_expired_deadline()."""

    async def test_list_expired_deadline_nominal(
        self, db_session, module, professor, course, questions_data
    ):
        """Un exercice avec deadline dans le passé apparaît dans la liste."""
        repo = SQLAlchemyExerciseRepository(db_session)
        e1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Expired", description=None, questions_data=questions_data,
        )
        past_deadline = datetime.now(timezone.utc) - timedelta(days=1)
        await repo.publish(e1.id, ExerciseStatus.PUBLISHED_AS_EXAM, course.id, past_deadline)

        page = await repo.list_with_expired_deadline()

        assert len(page.items) == 1
        assert page.items[0].id == e1.id

    async def test_list_expired_deadline_excludes_future(
        self, db_session, module, professor, course, questions_data
    ):
        """Un exercice avec deadline dans le futur n'apparaît pas."""
        repo = SQLAlchemyExerciseRepository(db_session)
        e1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Future", description=None, questions_data=questions_data,
        )
        future_deadline = datetime.now(timezone.utc) + timedelta(days=7)
        await repo.publish(e1.id, ExerciseStatus.PUBLISHED_AS_EXAM, course.id, future_deadline)

        page = await repo.list_with_expired_deadline()

        assert page.items == []

    async def test_list_expired_deadline_excludes_draft(
        self, db_session, module, professor, questions_data
    ):
        """Un exercice DRAFT n'apparaît pas même sans deadline."""
        repo = SQLAlchemyExerciseRepository(db_session)
        await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Draft", description=None, questions_data=questions_data,
        )

        page = await repo.list_with_expired_deadline()

        assert page.items == []


@pytest.mark.anyio
class TestExerciseRepositoryExistsProfessorExerciseInModule:
    """
    Tests de exists_professor_exercise_in_module() — câblage Partie 2/2
    (C2PCT), seul proxy réel d'ownership module disponible (aucune table
    d'enseignement M:N, cf. docstring de la méthode).
    """

    async def test_true_when_professor_has_exercise_in_module(
        self, db_session, module, professor, questions_data,
    ):
        repo = SQLAlchemyExerciseRepository(db_session)
        await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Ex1", description=None, questions_data=questions_data,
        )

        assert await repo.exists_professor_exercise_in_module(professor.id, module.id) is True

    async def test_false_when_professor_has_no_exercise_in_module(
        self, db_session, module, professor,
    ):
        repo = SQLAlchemyExerciseRepository(db_session)

        assert await repo.exists_professor_exercise_in_module(professor.id, module.id) is False

    async def test_false_when_exercise_in_module_belongs_to_another_professor(
        self, db_session, module, professor, other_professor, questions_data,
    ):
        """Un exercice existe bien dans le module, mais d'un AUTRE professeur -> jamais un faux positif."""
        repo = SQLAlchemyExerciseRepository(db_session)
        await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=other_professor.id,
            title="Ex1", description=None, questions_data=questions_data,
        )

        assert await repo.exists_professor_exercise_in_module(professor.id, module.id) is False


@pytest.mark.anyio
class TestExerciseRepositoryCountByStatus:
    """
    Tests de count_by_status() — câblage StatisticsService.get_platform_stats.
    Delta-based : la base de test est partagée entre les runs, jamais une
    valeur absolue attendue.
    """

    async def test_reflects_created_exercises_via_delta(
        self, db_session, module, professor, questions_data,
    ):
        repo = SQLAlchemyExerciseRepository(db_session)
        before = await repo.count_by_status()

        ex1 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Ex1", description=None, questions_data=questions_data,
        )
        ex2 = await repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Ex2", description=None, questions_data=questions_data,
        )
        await repo.publish(
            ex2.id, status=ExerciseStatus.PUBLISHED_AS_HOMEWORK, course_id=None, deadline=None,
        )

        after = await repo.count_by_status()

        # ex1 reste DRAFT (statut par défaut), ex2 passe PUBLISHED_AS_HOMEWORK.
        assert after.get(ExerciseStatus.DRAFT.value, 0) - before.get(ExerciseStatus.DRAFT.value, 0) == 1
        assert (
            after.get(ExerciseStatus.PUBLISHED_AS_HOMEWORK.value, 0)
            - before.get(ExerciseStatus.PUBLISHED_AS_HOMEWORK.value, 0)
            == 1
        )

    async def test_returns_dict_of_ints(self, db_session):
        repo = SQLAlchemyExerciseRepository(db_session)

        result = await repo.count_by_status()

        assert isinstance(result, dict)
        assert all(isinstance(v, int) for v in result.values())
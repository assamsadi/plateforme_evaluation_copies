"""
Tests du CourseRepository — couvre toutes les méthodes publiques :
- create (nominal, contrainte d'unicité module+group+semester)
- get_by_id (nominal, non trouvé)
- get_by_unique_key (nominal, non trouvé)
- list_by_module (nominal, filtre, pagination)
- list_by_professor (nominal, filtre, pagination)
- list_by_group (nominal, filtre, pagination)
- update_professor (nominal, non trouvé)
- is_student_in_course_group (nominal, student pas dans le groupe, course inexistant)
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.course import Course
from app.domain.models.identity.user import Student, Professor, UserRole, AcademicStatus
from app.domain.repositories.course_repository import SQLAlchemyCourseRepository
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
async def other_group(db_session, program):
    repo = SQLAlchemyGroupRepository(db_session)
    return await repo.create(program_id=program.id, label=f"OG{uuid.uuid4().hex[:6]}", academic_year="2025-2026")


@pytest.fixture
async def professor(db_session):
    """Crée un vrai Professor en base (joined table inheritance)."""
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
        department="Mathématiques",
        title="Pr",
        employee_number=f"EMP{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prof)
    await db_session.flush()
    return prof


@pytest.fixture
async def student_in_group(db_session, group):
    """Crée un vrai Student appartenant à `group`."""
    student = Student(
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
    db_session.add(student)
    await db_session.flush()
    return student


@pytest.fixture
async def student_in_other_group(db_session, other_group):
    """Crée un Student appartenant à `other_group` (pas le même groupe que le course)."""
    student = Student(
        id=uuid.uuid4(),
        role=UserRole.STUDENT,
        first_name="Diana",
        last_name="Lefevre",
        email=f"student2_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        student_number=f"STU{uuid.uuid4().hex[:6]}",
        group_id=other_group.id,
        enrollment_year=2025,
        academic_status=AcademicStatus.ACTIVE,
        level="L3",
    )
    db_session.add(student)
    await db_session.flush()
    return student


@pytest.mark.anyio
class TestCourseRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session, module, professor, group):
        repo = SQLAlchemyCourseRepository(db_session)
        course = await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )

        assert course.id is not None
        assert course.module_id == module.id
        assert course.professor_user_id == professor.id
        assert course.group_id == group.id
        assert course.semester == "S1-2025"
        assert course.created_at is not None

    async def test_create_duplicate_unique_key_raises_integrity_error(
        self, db_session, module, professor, group
    ):
        """Contrainte d'unicité (module_id, group_id, semester)."""
        repo = SQLAlchemyCourseRepository(db_session)
        await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )

        with pytest.raises(IntegrityError):
            await repo.create(
                module_id=module.id,
                professor_user_id=professor.id,
                group_id=group.id,
                semester="S1-2025",
            )
        await db_session.rollback()

    async def test_create_same_module_different_semester_ok(
        self, db_session, module, professor, group
    ):
        """Même module+group mais semester différent : autorisé."""
        repo = SQLAlchemyCourseRepository(db_session)
        c1 = await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )
        c2 = await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S2-2025",
        )

        assert c1.id != c2.id


@pytest.mark.anyio
class TestCourseRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session, module, professor, group):
        repo = SQLAlchemyCourseRepository(db_session)
        created = await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )

        found = await repo.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.module_id == module.id
        assert found.semester == "S1-2025"

    async def test_get_by_id_not_found_returns_none(self, db_session):
        repo = SQLAlchemyCourseRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestCourseRepositoryGetByUniqueKey:
    """Tests de la méthode get_by_unique_key()."""

    async def test_get_by_unique_key_found(self, db_session, module, professor, group):
        repo = SQLAlchemyCourseRepository(db_session)
        await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )

        found = await repo.get_by_unique_key(module.id, group.id, "S1-2025")

        assert found is not None
        assert found.module_id == module.id
        assert found.group_id == group.id
        assert found.semester == "S1-2025"

    async def test_get_by_unique_key_not_found_returns_none(self, db_session, module, group):
        repo = SQLAlchemyCourseRepository(db_session)

        found = await repo.get_by_unique_key(module.id, group.id, "NONEXISTENT")

        assert found is None


@pytest.mark.anyio
class TestCourseRepositoryListByModule:
    """Tests de la méthode list_by_module()."""

    async def test_list_by_module_nominal(self, db_session, module, professor, group, other_group):
        repo = SQLAlchemyCourseRepository(db_session)
        c1 = await repo.create(module_id=module.id, professor_user_id=professor.id, group_id=group.id, semester="S1")
        c2 = await repo.create(module_id=module.id, professor_user_id=professor.id, group_id=other_group.id, semester="S1")

        page = await repo.list_by_module(module.id)

        assert len(page.items) == 2
        assert all(c.module_id == module.id for c in page.items)

    async def test_list_by_module_empty(self, db_session, module):
        repo = SQLAlchemyCourseRepository(db_session)

        page = await repo.list_by_module(module.id)

        assert page.items == []
        assert page.has_more is False

    async def test_list_by_module_pagination(self, db_session, module, professor, group):
        repo = SQLAlchemyCourseRepository(db_session)
        for i in range(5):
            await repo.create(
                module_id=module.id,
                professor_user_id=professor.id,
                group_id=group.id,
                semester=f"S{i}",
            )

        first_page = await repo.list_by_module(module.id, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_by_module(module.id, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id


@pytest.mark.anyio
class TestCourseRepositoryListByProfessor:
    """Tests de la méthode list_by_professor()."""

    async def test_list_by_professor_nominal(self, db_session, module, professor, other_professor, group):
        repo = SQLAlchemyCourseRepository(db_session)
        c1 = await repo.create(module_id=module.id, professor_user_id=professor.id, group_id=group.id, semester="S1")
        c2 = await repo.create(module_id=module.id, professor_user_id=other_professor.id, group_id=group.id, semester="S2")

        page = await repo.list_by_professor(professor.id)

        assert len(page.items) == 1
        assert page.items[0].id == c1.id
        assert page.items[0].professor_user_id == professor.id

    async def test_list_by_professor_empty(self, db_session, professor):
        repo = SQLAlchemyCourseRepository(db_session)

        page = await repo.list_by_professor(professor.id)

        assert page.items == []
        assert page.has_more is False


@pytest.mark.anyio
class TestCourseRepositoryListByGroup:
    """Tests de la méthode list_by_group()."""

    async def test_list_by_group_nominal(self, db_session, module, professor, group, other_group):
        repo = SQLAlchemyCourseRepository(db_session)
        c1 = await repo.create(module_id=module.id, professor_user_id=professor.id, group_id=group.id, semester="S1")
        c2 = await repo.create(module_id=module.id, professor_user_id=professor.id, group_id=other_group.id, semester="S1")

        page = await repo.list_by_group(group.id)

        assert len(page.items) == 1
        assert page.items[0].id == c1.id
        assert page.items[0].group_id == group.id

    async def test_list_by_group_empty(self, db_session, group):
        repo = SQLAlchemyCourseRepository(db_session)

        page = await repo.list_by_group(group.id)

        assert page.items == []
        assert page.has_more is False


@pytest.mark.anyio
class TestCourseRepositoryUpdateProfessor:
    """Tests de la méthode update_professor()."""

    async def test_update_professor_nominal(self, db_session, module, professor, other_professor, group):
        repo = SQLAlchemyCourseRepository(db_session)
        created = await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )

        updated = await repo.update_professor(created.id, other_professor.id)

        assert updated is not None
        assert updated.id == created.id
        assert updated.professor_user_id == other_professor.id

    async def test_update_professor_not_found_returns_none(self, db_session, professor):
        repo = SQLAlchemyCourseRepository(db_session)

        result = await repo.update_professor(uuid.uuid4(), professor.id)

        assert result is None


@pytest.mark.anyio
class TestCourseRepositoryIsStudentInCourseGroup:
    """Tests de la méthode is_student_in_course_group()."""

    async def test_student_in_course_group_true(
        self, db_session, module, professor, group, student_in_group
    ):
        """L'étudiant appartient au groupe du cours → True."""
        repo = SQLAlchemyCourseRepository(db_session)
        course = await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )

        result = await repo.is_student_in_course_group(course.id, student_in_group.id)

        assert result is True

    async def test_student_not_in_course_group_false(
        self, db_session, module, professor, group, student_in_other_group
    ):
        """L'étudiant appartient à un autre groupe → False."""
        repo = SQLAlchemyCourseRepository(db_session)
        course = await repo.create(
            module_id=module.id,
            professor_user_id=professor.id,
            group_id=group.id,
            semester="S1-2025",
        )

        result = await repo.is_student_in_course_group(course.id, student_in_other_group.id)

        assert result is False

    async def test_course_not_found_returns_false(self, db_session, student_in_group):
        """Course inexistant → False."""
        repo = SQLAlchemyCourseRepository(db_session)

        result = await repo.is_student_in_course_group(uuid.uuid4(), student_in_group.id)

        assert result is False
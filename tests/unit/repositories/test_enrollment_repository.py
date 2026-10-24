"""
Tests du EnrollmentRepository — couvre toutes les méthodes publiques :
- create (nominal, contrainte d'unicité student+module)
- get_by_id (nominal, non trouvé)
- get_by_student_and_module (nominal, non trouvé)
- is_student_enrolled_and_active (nominal, inactif, non inscrit)
- list_by_student (nominal, filtre, pagination)
- list_by_module (nominal, filtre, pagination)
- deactivate (nominal, non trouvé)
- reactivate (nominal, non trouvé)
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.enrollment import Enrollment
from app.domain.models.identity.user import Student, UserRole, AcademicStatus
from app.domain.repositories.enrollment_repository import SQLAlchemyEnrollmentRepository
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
async def other_module(db_session, program):
    repo = SQLAlchemyModuleRepository(db_session)
    return await repo.create(program_id=program.id, name=f"Other Module {uuid.uuid4().hex[:8]}", code=f"OM{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def group(db_session, program):
    repo = SQLAlchemyGroupRepository(db_session)
    return await repo.create(program_id=program.id, label=f"G{uuid.uuid4().hex[:6]}", academic_year="2025-2026")


@pytest.fixture
async def student(db_session, group):
    s = Student(
        id=uuid.uuid4(),
        role=UserRole.STUDENT,
        first_name="Alice",
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
async def other_student(db_session, group):
    s = Student(
        id=uuid.uuid4(),
        role=UserRole.STUDENT,
        first_name="Bob",
        last_name="Martin",
        email=f"student2_{uuid.uuid4().hex[:8]}@test.edu",
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


@pytest.mark.anyio
class TestEnrollmentRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        enrollment = await repo.create(student_id=student.id, module_id=module.id)

        assert enrollment.id is not None
        assert enrollment.student_id == student.id
        assert enrollment.module_id == module.id
        assert enrollment.is_active is True
        assert enrollment.enrolled_at is not None

    async def test_create_duplicate_raises_integrity_error(self, db_session, student, module):
        """Contrainte d'unicité (student_id, module_id)."""
        repo = SQLAlchemyEnrollmentRepository(db_session)
        await repo.create(student_id=student.id, module_id=module.id)

        with pytest.raises(IntegrityError):
            await repo.create(student_id=student.id, module_id=module.id)
        await db_session.rollback()

    async def test_create_same_student_different_module_ok(self, db_session, student, module, other_module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        e1 = await repo.create(student_id=student.id, module_id=module.id)
        e2 = await repo.create(student_id=student.id, module_id=other_module.id)

        assert e1.id != e2.id

    async def test_create_same_module_different_student_ok(self, db_session, student, other_student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        e1 = await repo.create(student_id=student.id, module_id=module.id)
        e2 = await repo.create(student_id=other_student.id, module_id=module.id)

        assert e1.id != e2.id


@pytest.mark.anyio
class TestEnrollmentRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        created = await repo.create(student_id=student.id, module_id=module.id)

        found = await repo.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.student_id == student.id
        assert found.module_id == module.id

    async def test_get_by_id_not_found_returns_none(self, db_session):
        repo = SQLAlchemyEnrollmentRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestEnrollmentRepositoryGetByStudentAndModule:
    """Tests de la méthode get_by_student_and_module()."""

    async def test_get_by_student_and_module_found(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        await repo.create(student_id=student.id, module_id=module.id)

        found = await repo.get_by_student_and_module(student.id, module.id)

        assert found is not None
        assert found.student_id == student.id
        assert found.module_id == module.id

    async def test_get_by_student_and_module_not_found_returns_none(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)

        found = await repo.get_by_student_and_module(student.id, module.id)

        assert found is None


@pytest.mark.anyio
class TestEnrollmentRepositoryIsStudentEnrolledAndActive:
    """Tests de la méthode is_student_enrolled_and_active()."""

    async def test_active_enrollment_returns_true(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        await repo.create(student_id=student.id, module_id=module.id)

        result = await repo.is_student_enrolled_and_active(student.id, module.id)

        assert result is True

    async def test_inactive_enrollment_returns_false(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        enrollment = await repo.create(student_id=student.id, module_id=module.id)
        await repo.deactivate(enrollment.id)

        result = await repo.is_student_enrolled_and_active(student.id, module.id)

        assert result is False

    async def test_not_enrolled_returns_false(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)

        result = await repo.is_student_enrolled_and_active(student.id, module.id)

        assert result is False


@pytest.mark.anyio
class TestEnrollmentRepositoryListByStudent:
    """Tests de la méthode list_by_student()."""

    async def test_list_by_student_nominal(self, db_session, student, module, other_module, other_student):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        e1 = await repo.create(student_id=student.id, module_id=module.id)
        e2 = await repo.create(student_id=student.id, module_id=other_module.id)
        e3 = await repo.create(student_id=other_student.id, module_id=module.id)

        page = await repo.list_by_student(student.id)

        assert len(page.items) == 2
        assert all(e.student_id == student.id for e in page.items)

    async def test_list_by_student_empty(self, db_session, student):
        repo = SQLAlchemyEnrollmentRepository(db_session)

        page = await repo.list_by_student(student.id)

        assert page.items == []
        assert page.has_more is False

    async def test_list_by_student_pagination(self, db_session, student, program):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        module_repo = SQLAlchemyModuleRepository(db_session)
        for i in range(5):
            m = await module_repo.create(program_id=program.id, name=f"Mod {i} {uuid.uuid4().hex[:6]}", code=f"M{i}{uuid.uuid4().hex[:4]}")
            await repo.create(student_id=student.id, module_id=m.id)

        first_page = await repo.list_by_student(student.id, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_by_student(student.id, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id


@pytest.mark.anyio
class TestEnrollmentRepositoryListByModule:
    """Tests de la méthode list_by_module()."""

    async def test_list_by_module_nominal(self, db_session, student, other_student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        e1 = await repo.create(student_id=student.id, module_id=module.id)
        e2 = await repo.create(student_id=other_student.id, module_id=module.id)

        page = await repo.list_by_module(module.id)

        assert len(page.items) == 2
        assert all(e.module_id == module.id for e in page.items)

    async def test_list_by_module_empty(self, db_session, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)

        page = await repo.list_by_module(module.id)

        assert page.items == []
        assert page.has_more is False


@pytest.mark.anyio
class TestEnrollmentRepositoryDeactivate:
    """Tests de la méthode deactivate()."""

    async def test_deactivate_nominal(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        created = await repo.create(student_id=student.id, module_id=module.id)
        assert created.is_active is True

        deactivated = await repo.deactivate(created.id)

        assert deactivated is not None
        assert deactivated.id == created.id
        assert deactivated.is_active is False

    async def test_deactivate_not_found_returns_none(self, db_session):
        repo = SQLAlchemyEnrollmentRepository(db_session)

        result = await repo.deactivate(uuid.uuid4())

        assert result is None


@pytest.mark.anyio
class TestEnrollmentRepositoryReactivate:
    """Tests de la méthode reactivate()."""

    async def test_reactivate_nominal(self, db_session, student, module):
        repo = SQLAlchemyEnrollmentRepository(db_session)
        created = await repo.create(student_id=student.id, module_id=module.id)
        await repo.deactivate(created.id)
        assert created.is_active is False

        reactivated = await repo.reactivate(created.id)

        assert reactivated is not None
        assert reactivated.id == created.id
        assert reactivated.is_active is True

    async def test_reactivate_not_found_returns_none(self, db_session):
        repo = SQLAlchemyEnrollmentRepository(db_session)

        result = await repo.reactivate(uuid.uuid4())

        assert result is None

    async def test_reactivate_does_not_change_enrolled_at(self, db_session, student, module):
        """reactivate ne remet pas à jour enrolled_at (garde l'historique)."""
        repo = SQLAlchemyEnrollmentRepository(db_session)
        created = await repo.create(student_id=student.id, module_id=module.id)
        original_enrolled_at = created.enrolled_at

        await repo.deactivate(created.id)
        reactivated = await repo.reactivate(created.id)

        assert reactivated.enrolled_at == original_enrolled_at
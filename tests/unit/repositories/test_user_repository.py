"""
Tests du UserRepository — couvre count_by_role() (câblage StatisticsService.
get_platform_stats) et list_users()/update(is_active=...) (câblage gestion
admin des comptes). Delta-based pour count_by_role : la base de test est
partagée entre les runs, jamais une valeur absolue attendue.
"""
import uuid

import pytest

from app.domain.models.identity.user import AcademicStatus, Admin, Professor, Student, UserRole
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository


@pytest.fixture
async def program(db_session):
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Test Program {uuid.uuid4().hex[:8]}", code=f"TP{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def group(db_session, program):
    repo = SQLAlchemyGroupRepository(db_session)
    return await repo.create(program_id=program.id, label=f"G{uuid.uuid4().hex[:6]}", academic_year="2025-2026")


@pytest.mark.anyio
class TestUserRepositoryCountByRole:
    async def test_reflects_created_users_via_delta(self, db_session, group):
        repo = SQLAlchemyUserRepository(db_session)
        before = await repo.count_by_role()

        student = Student(
            id=uuid.uuid4(), role=UserRole.STUDENT, first_name="Alice", last_name="Dupont",
            email=f"student_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
            student_number=f"STU{uuid.uuid4().hex[:6]}", group_id=group.id,
            enrollment_year=2025, academic_status=AcademicStatus.ACTIVE, level="L3",
        )
        professor = Professor(
            id=uuid.uuid4(), role=UserRole.PROFESSOR, first_name="Bob", last_name="Martin",
            email=f"prof_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
            department="Informatique", title="Dr", employee_number=f"EMP{uuid.uuid4().hex[:6]}",
        )
        admin = Admin(
            id=uuid.uuid4(), role=UserRole.ADMIN, first_name="Charlie", last_name="Bernard",
            email=f"admin_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
        )
        db_session.add_all([student, professor, admin])
        await db_session.flush()

        after = await repo.count_by_role()

        assert after.get(UserRole.STUDENT.value, 0) - before.get(UserRole.STUDENT.value, 0) == 1
        assert after.get(UserRole.PROFESSOR.value, 0) - before.get(UserRole.PROFESSOR.value, 0) == 1
        assert after.get(UserRole.ADMIN.value, 0) - before.get(UserRole.ADMIN.value, 0) == 1

    async def test_returns_dict_of_ints(self, db_session):
        repo = SQLAlchemyUserRepository(db_session)

        result = await repo.count_by_role()

        assert isinstance(result, dict)
        assert all(isinstance(v, int) for v in result.values())


@pytest.mark.anyio
class TestUserRepositoryIsActiveDefault:
    async def test_new_user_defaults_to_active(self, db_session):
        repo = SQLAlchemyUserRepository(db_session)

        admin = await repo.create_admin(
            email=f"admin_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
            first_name="Charlie", last_name="Bernard",
        )

        assert admin.is_active is True

    async def test_update_can_toggle_is_active(self, db_session):
        """update(**kwargs) est déjà générique — réutilisé pour is_active, aucune méthode dédiée nécessaire."""
        repo = SQLAlchemyUserRepository(db_session)
        admin = await repo.create_admin(
            email=f"admin_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
            first_name="Charlie", last_name="Bernard",
        )

        deactivated = await repo.update(admin.id, is_active=False)
        assert deactivated.is_active is False

        reactivated = await repo.update(admin.id, is_active=True)
        assert reactivated.is_active is True


@pytest.mark.anyio
class TestUserRepositoryListUsers:
    async def test_empty_role_filter_no_match(self, db_session):
        repo = SQLAlchemyUserRepository(db_session)
        marker_email = f"nomatch_{uuid.uuid4().hex[:8]}@test.edu"
        await repo.create_admin(
            email=marker_email, hashed_password="hashed_pw", first_name="Z", last_name="Z",
        )

        page = await repo.list_users(role=UserRole.PROFESSOR, limit=200)

        assert marker_email not in {u.email for u in page.items}

    async def test_filters_by_role_via_delta(self, db_session):
        repo = SQLAlchemyUserRepository(db_session)
        marker_email = f"prof_{uuid.uuid4().hex[:8]}@test.edu"
        created = await repo.create_professor(
            email=marker_email, hashed_password="hashed_pw", first_name="Bob", last_name="Martin",
            department="Info", title="Dr", employee_number=f"EMP{uuid.uuid4().hex[:6]}",
        )

        page = await repo.list_users(role=UserRole.PROFESSOR, limit=200)

        assert any(u.id == created.id for u in page.items)
        assert all(u.role == UserRole.PROFESSOR for u in page.items)

    async def test_no_role_filter_includes_all_roles(self, db_session, group):
        repo = SQLAlchemyUserRepository(db_session)
        student = Student(
            id=uuid.uuid4(), role=UserRole.STUDENT, first_name="Alice", last_name="Dupont",
            email=f"student_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
            student_number=f"STU{uuid.uuid4().hex[:6]}", group_id=group.id,
            enrollment_year=2025, academic_status=AcademicStatus.ACTIVE, level="L3",
        )
        db_session.add(student)
        await db_session.flush()

        page = await repo.list_users(limit=500)

        assert any(u.id == student.id for u in page.items)

    async def test_pagination_cursor(self, db_session):
        repo = SQLAlchemyUserRepository(db_session)
        for _ in range(3):
            await repo.create_admin(
                email=f"admin_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
                first_name="A", last_name="B",
            )

        first_page = await repo.list_users(role=UserRole.ADMIN, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_users(role=UserRole.ADMIN, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) >= 1
        assert second_page.items[0].id != first_page.items[0].id

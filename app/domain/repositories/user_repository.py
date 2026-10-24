"""
Repository User — UN SEUL repository pour toute la hiérarchie
User/Student/Professor/Admin. SQLAlchemy résout automatiquement le bon
sous-type via polymorphic_on=role (configuré dans identity/user.py) :
get_by_id() sur un student_id retourne directement une instance Student,
sans code de dispatch manuel ici.

Volontairement AUCUNE vérification de mot de passe ici (pas de
verify_credentials()) — un repository ne fait que de l'accès aux
données, jamais de logique de sécurité (§7, séparation stricte des
responsabilités). C'est auth_service.py qui orchestre :
repository.get_by_email() -> security.verify_password().
"""
import uuid
from typing import Protocol

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import with_polymorphic

from app.domain.models.academic.group import Group
from app.domain.models.academic.program import Program
from app.domain.models.identity.user import Admin, Professor, Student, User, UserRole
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)

# Groupe de repli pour l'auto-inscription publique (POST /auth/register/student)
# : group_id est NOT NULL en base (FK groups.id), mais aucun endpoint public
# ne permet à un étudiant anonyme de choisir son vrai groupe avant
# authentification. Ce groupe sentinelle doit être créé une fois via
# scripts/ensure_unassigned_group.py — jamais créé à la volée ici, pour ne
# jamais masquer une erreur de configuration derrière une création silencieuse.
UNASSIGNED_PROGRAM_CODE = "UNASSIGNED"
UNASSIGNED_GROUP_LABEL = "Non assigné"


class UserRepositoryProtocol(Protocol):
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...
    async def get_by_id_with_role_details(self, user_id: uuid.UUID) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def get_by_student_number(self, student_number: str) -> Student | None: ...
    async def get_by_employee_number(self, employee_number: str) -> Professor | None: ...
    async def list_students_by_group(
        self, group_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Student]: ...
    async def create_student(
        self,
        email: str,
        hashed_password: str,
        first_name: str,
        last_name: str,
        student_number: str,
        group_id: uuid.UUID | None,
        enrollment_year: int,
        level: str,
    ) -> Student: ...
    async def create_professor(
        self,
        email: str,
        hashed_password: str,
        first_name: str,
        last_name: str,
        department: str,
        title: str,
        employee_number: str,
        office_location: str | None = None,
        specialty: str | None = None,
    ) -> Professor: ...
    async def create_admin(
        self, email: str, hashed_password: str, first_name: str, last_name: str
    ) -> Admin: ...
    async def update(self, user_id: uuid.UUID, **kwargs) -> User | None: ...
    async def count_by_role(self) -> dict[str, int]: ...
    async def list_users(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE, role: UserRole | None = None,
    ) -> CursorPage[User]: ...


class SQLAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_id_with_role_details(self, user_id: uuid.UUID) -> User | None:
        """
        Comme get_by_id, mais force le JOIN eager vers la table du sous-type
        (students/professors/admins) via with_polymorphic("*"). Nécessaire
        dès qu'on doit lire un champ spécifique au rôle (department,
        student_number...) juste après le fetch : sans ça, SQLAlchemy tente
        un lazy-load synchrone au premier accès à l'attribut, ce qui casse
        en contexte async (MissingGreenlet) — get_by_id seul suffit tant
        qu'on ne lit que les champs de la table users de base.
        """
        entity = with_polymorphic(User, "*")
        result = await self._session.execute(select(entity).where(entity.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_student_number(self, student_number: str) -> Student | None:
        """
        Bug corrigé (500 réel constaté à la création admin) : student_number
        est UNIQUE en base mais n'était jamais pré-vérifié par UserService.
        register_student — une collision remontait comme une IntegrityError
        asyncpg brute (jamais un ValueError), donc un 500 plutôt qu'un 400
        propre. Même rôle que get_by_email ci-dessus.
        """
        result = await self._session.execute(select(Student).where(Student.student_number == student_number))
        return result.scalar_one_or_none()

    async def get_by_employee_number(self, employee_number: str) -> Professor | None:
        """Même correctif que get_by_student_number, pour employee_number (Professor)."""
        result = await self._session.execute(select(Professor).where(Professor.employee_number == employee_number))
        return result.scalar_one_or_none()

    async def list_students_by_group(
        self, group_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Student]:
        query = select(Student).where(Student.group_id == group_id)
        query = query.order_by(Student.created_at, Student.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Student.created_at, Student.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda s: (s.created_at, s.id))

    async def create_student(
        self,
        email: str,
        hashed_password: str,
        first_name: str,
        last_name: str,
        student_number: str,
        group_id: uuid.UUID | None,
        enrollment_year: int,
        level: str,
    ) -> Student:
        resolved_group_id = group_id if group_id is not None else await self._get_unassigned_group_id()
        student = Student(
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            student_number=student_number,
            group_id=resolved_group_id,
            enrollment_year=enrollment_year,
            level=level,
        )
        self._session.add(student)
        await self._session.flush()
        return student

    async def _get_unassigned_group_id(self) -> uuid.UUID:
        result = await self._session.execute(
            select(Group.id)
            .join(Program, Group.program_id == Program.id)
            .where(Program.code == UNASSIGNED_PROGRAM_CODE)
            .limit(1)
        )
        group_id = result.scalar_one_or_none()
        if group_id is None:
            raise ValueError(
                "Aucun groupe 'non assigné' n'existe — lancez "
                "scripts/ensure_unassigned_group.py avant d'accepter des "
                "inscriptions publiques."
            )
        return group_id

    async def create_professor(
        self,
        email: str,
        hashed_password: str,
        first_name: str,
        last_name: str,
        department: str,
        title: str,
        employee_number: str,
        office_location: str | None = None,
        specialty: str | None = None,
    ) -> Professor:
        professor = Professor(
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            department=department,
            title=title,
            employee_number=employee_number,
            office_location=office_location,
            specialty=specialty,
        )
        self._session.add(professor)
        await self._session.flush()
        return professor

    async def create_admin(
        self, email: str, hashed_password: str, first_name: str, last_name: str
    ) -> Admin:
        admin = Admin(
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
        )
        self._session.add(admin)
        await self._session.flush()
        return admin

    async def update(self, user_id: uuid.UUID, **kwargs) -> User | None:
        """
        get_by_id_with_role_details (pas get_by_id) — même piège que documenté
        sur cette méthode : les appelants (update_student/update_professor,
        UserService) renvoient ensuite StudentPublic/ProfessorPublic, qui
        lisent des champs spécifiques au rôle (ex. academic_status) JAMAIS
        touchés par les kwargs de mise à jour (ex. changer juste l'email).
        Avec get_by_id seul, ces colonnes restent non chargées (pas de JOIN
        polymorphique) et leur lecture par Pydantic hors contexte async
        explicite plante avec MissingGreenlet — constaté en test réel
        (2026-08-30, création d'un étudiant puis changement d'email).
        """
        user = await self.get_by_id_with_role_details(user_id)
        if not user:
            return None
        for key, value in kwargs.items():
            setattr(user, key, value)
        await self._session.flush()
        return user

    async def count_by_role(self) -> dict[str, int]:
        """
        Câblage StatisticsService.get_platform_stats — seuls les rôles
        réellement présents en base apparaissent ici (GROUP BY), jamais les
        3 rôles forcés à 0 par défaut : c'est au service de compléter les
        rôles absents (contrat de sortie API stable), pas au repository.
        """
        stmt = select(User.role, func.count()).group_by(User.role)
        result = await self._session.execute(stmt)
        return {role.value: count for role, count in result.all()}

    async def list_users(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE, role: UserRole | None = None,
    ) -> CursorPage[User]:
        """
        Câblage GET /admin/users — select(User) polymorphique (résout
        automatiquement Student/Professor/Admin via role, cf. docstring
        module), même pattern de curseur que list_students_by_group.
        """
        query = select(User)
        if role is not None:
            query = query.where(User.role == role)
        query = query.order_by(User.created_at, User.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(User.created_at, User.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda u: (u.created_at, u.id))
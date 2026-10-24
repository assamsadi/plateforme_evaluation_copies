"""
Hiérarchie User -> Student / Professor / Admin, en Joined Table Inheritance
(décision actée : évite les colonnes NULL selon le rôle, chaque sous-type
garde ses propres champs dans sa propre table, reliée à `users` par FK).

`role` est la colonne discriminante (polymorphic_on) : SQLAlchemy charge
automatiquement la bonne sous-classe (Student/Professor/Admin) selon sa
valeur, sans jamais avoir à tester le rôle manuellement dans le code métier.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Integer, Sequence, String, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class UserRole(StrEnum):
    STUDENT = "student"
    PROFESSOR = "professor"
    ADMIN = "admin"


class AcademicStatus(StrEnum):
    """Statut administratif de l'étudiant — un statut SUSPENDED doit être
    vérifié par submission_service.py avant d'autoriser une soumission,
    même si l'étudiant a toujours un Enrollment actif sur le module."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    GRADUATED = "graduated"
    DROPPED_OUT = "dropped_out"


class User(Base, UUIDPKMixin, TimestampMixin):
    """Table de base : champs communs à tous les rôles."""
    __tablename__ = "users"

    role: Mapped[UserRole] = mapped_column(
        PgEnum(UserRole, name="user_role"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    totp_secret: Mapped[str | None] = mapped_column(String(32), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    totp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totp_last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Gestion admin des comptes (désactivation) — sur User de base, pas
    # Student.academic_status (scopé Student, sémantique académique, pas
    # autorisation d'authentification, cf. docstring migration
    # d6e7f8a9b0c1). Vérifié à la connexion (UserService.authenticate) ET
    # sur chaque requête authentifiée déjà en cours (get_current_active_user)
    # — un token émis avant désactivation ne doit pas rester valable jusqu'à
    # son expiration naturelle.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __mapper_args__ = {
        "polymorphic_on": role,
    }


class Student(User):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    student_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id"), nullable=False
    )
    enrollment_year: Mapped[int] = mapped_column(Integer, nullable=False)
    academic_status: Mapped[AcademicStatus] = mapped_column(
        PgEnum(AcademicStatus, name="academic_status"),
        nullable=False,
        default=AcademicStatus.ACTIVE,
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)

    __mapper_args__ = {"polymorphic_identity": UserRole.STUDENT}


class Professor(User):
    __tablename__ = "professors"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    employee_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    office_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    specialty: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __mapper_args__ = {"polymorphic_identity": UserRole.PROFESSOR}


class Admin(User):
    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    # Identifiant lisible séquentiel (audit "ids manquants" — seule table
    # identity/ sans équivalent de student_number/employee_number) — séquence
    # Postgres dédiée (admin_number_seq), jamais un COUNT(*)+1 applicatif
    # (même risque de course que get_next_attempt_number, cf. son docstring
    # dans submission_repository.py).
    admin_number: Mapped[int] = mapped_column(
        Integer, Sequence("admin_number_seq"), unique=True, nullable=False
    )

    __mapper_args__ = {"polymorphic_identity": UserRole.ADMIN}
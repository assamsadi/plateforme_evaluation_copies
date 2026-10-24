"""
Tests unitaires pour log_security_policy.py (§17).

Vérifie la règle de sécurité d'accès aux AgentDecisionLog :
- Statut DRAFT (exercice non publié) : réservé au professeur créateur UNIQUEMENT (Admin et Étudiants rejetés).
- Statut PUBLISHED / ARCHIVED : professeur créateur ET Admin autorisés, Étudiants et profs tiers rejetés.
"""
import uuid
import pytest

from app.auth.log_security_policy import authorize_agent_log_access
from app.core.exceptions import ForbiddenError
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.identity.user import Admin, Professor, Student, UserRole


def _make_exercise(status: ExerciseStatus, professor_id: uuid.UUID) -> Exercise:
    e = Exercise()
    e.id = uuid.uuid4()
    e.status = status
    e.created_by_professor_id = professor_id
    return e


def _make_professor(user_id: uuid.UUID | None = None) -> Professor:
    p = Professor()
    p.id = user_id or uuid.uuid4()
    p.role = UserRole.PROFESSOR
    return p


def _make_admin(user_id: uuid.UUID | None = None) -> Admin:
    a = Admin()
    a.id = user_id or uuid.uuid4()
    a.role = UserRole.ADMIN
    return a


def _make_student(user_id: uuid.UUID | None = None) -> Student:
    s = Student()
    s.id = user_id or uuid.uuid4()
    s.role = UserRole.STUDENT
    return s


def test_draft_exercise_creator_access_allowed():
    prof_id = uuid.uuid4()
    exercise = _make_exercise(ExerciseStatus.DRAFT, prof_id)
    prof = _make_professor(prof_id)

    # Doit s'exécuter sans lever d'exception
    authorize_agent_log_access(prof, exercise)


def test_draft_exercise_admin_access_forbidden():
    prof_id = uuid.uuid4()
    exercise = _make_exercise(ExerciseStatus.DRAFT, prof_id)
    admin = _make_admin()

    with pytest.raises(ForbiddenError, match="DRAFT.*réservé au professeur créateur"):
        authorize_agent_log_access(admin, exercise)


def test_draft_exercise_other_prof_access_forbidden():
    prof_id = uuid.uuid4()
    exercise = _make_exercise(ExerciseStatus.DRAFT, prof_id)
    other_prof = _make_professor()

    with pytest.raises(ForbiddenError):
        authorize_agent_log_access(other_prof, exercise)


def test_published_exercise_creator_access_allowed():
    prof_id = uuid.uuid4()
    exercise = _make_exercise(ExerciseStatus.PUBLISHED_AS_EXAM, prof_id)
    prof = _make_professor(prof_id)

    authorize_agent_log_access(prof, exercise)


def test_published_exercise_admin_access_allowed():
    prof_id = uuid.uuid4()
    exercise = _make_exercise(ExerciseStatus.PUBLISHED_AS_EXAM, prof_id)
    admin = _make_admin()

    # Admin autorisé après publication
    authorize_agent_log_access(admin, exercise)


def test_published_exercise_student_access_forbidden():
    prof_id = uuid.uuid4()
    exercise = _make_exercise(ExerciseStatus.PUBLISHED_AS_EXAM, prof_id)
    student = _make_student()

    with pytest.raises(ForbiddenError):
        authorize_agent_log_access(student, exercise)

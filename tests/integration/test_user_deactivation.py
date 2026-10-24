"""
Test d'intégration RÉEL (DB réelle, hachage de mot de passe réel, aucun
mock de UserService/UserRepository) — preuve que la désactivation d'un
compte bloque effectivement l'authentification, comme demandé par le
ticket ("testé réellement (tentative de connexion après désactivation)").

Utilise le client HTTP non authentifié (`client`) + `_override_deps`
(autouse, cf. tests/integration/conftest.py) qui branche get_db sur la
MÊME session transactionnelle que db_session — le vrai UserService /
SQLAlchemyUserRepository sont donc exercés de bout en bout via /auth/login,
pas des mocks.
"""
import uuid

import pytest

from app.core.security import hash_password
from app.domain.models.identity.user import AcademicStatus, Student, UserRole
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
async def real_student(db_session):
    program_repo = SQLAlchemyProgramRepository(db_session)
    group_repo = SQLAlchemyGroupRepository(db_session)
    program = await program_repo.create(name=f"Prog {uuid.uuid4().hex[:8]}", code=f"PR{uuid.uuid4().hex[:6]}")
    group = await group_repo.create(program_id=program.id, label=f"G{uuid.uuid4().hex[:6]}", academic_year="2025-2026")

    student = Student(
        id=uuid.uuid4(), role=UserRole.STUDENT, first_name="Alice", last_name="Dupont",
        email=f"alice_{uuid.uuid4().hex[:8]}@test.edu", hashed_password=hash_password(PASSWORD),
        student_number=f"STU{uuid.uuid4().hex[:6]}", group_id=group.id,
        enrollment_year=2025, academic_status=AcademicStatus.ACTIVE, level="L3", is_active=True,
    )
    db_session.add(student)
    await db_session.flush()
    return student


@pytest.mark.anyio
async def test_login_succeeds_while_account_is_active(client, real_student):
    response = await client.post("/api/v1/auth/login", json={
        "email": real_student.email, "password": PASSWORD,
    })

    assert response.status_code == 200
    assert "access_token" in response.json()


@pytest.mark.anyio
async def test_login_blocked_after_deactivation(client, db_session, real_student):
    """Le cœur de la preuve demandée par le ticket : désactivation -> nouvelle tentative de connexion -> refusée."""
    user_repo = SQLAlchemyUserRepository(db_session)
    await user_repo.update(real_student.id, is_active=False)

    response = await client.post("/api/v1/auth/login", json={
        "email": real_student.email, "password": PASSWORD,
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "Compte désactivé"


@pytest.mark.anyio
async def test_wrong_password_on_deactivated_account_still_generic_error(client, db_session, real_student):
    """Ne révèle jamais qu'un compte est désactivé à quelqu'un qui n'a pas le bon mot de passe."""
    user_repo = SQLAlchemyUserRepository(db_session)
    await user_repo.update(real_student.id, is_active=False)

    response = await client.post("/api/v1/auth/login", json={
        "email": real_student.email, "password": "wrong-password",
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "Identifiants invalides"


# Note : un test bout-en-bout "token émis avant désactivation, rejeté après"
# nécessiterait un aller-retour HTTP via /auth/mfa/status (ou toute autre
# route protégée), qui passe par get_current_user -> decode_token -> vérif
# blacklist Redis (app/core/security.py::_is_blacklisted) — AUCUN Redis
# réel n'est disponible dans cet environnement de test (vérifié : aucun
# test existant du projet n'exerce le chemin get_current_user réel via un
# vrai token pour cette raison, tous utilisent soit les clients à rôle
# mocké — dependency_overrides bypassent decode_token entièrement — soit
# des services mockés). Le blocage par is_active lui-même (distinct du
# décodage/blacklist) est prouvé sans dépendance Redis dans
# tests/unit/api/test_deps.py::test_get_current_active_user_rejects_
# inactive_user, qui appelle get_current_active_user directement.

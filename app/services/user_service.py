import uuid
from typing import Any
from datetime import datetime, timezone

import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    verify_password,
    hash_password,
)
from app.domain.models.identity.user import User, Student, Professor, Admin, UserRole
from app.domain.repositories.pagination import CursorPage, DEFAULT_PAGE_SIZE
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.repositories.audit_log_repository import AuditLogRepositoryProtocol
from app.domain.schemas.auth_schemas import (
    AdminCreate,
    AdminUpdate,
    LoginRequest,
    ProfessorCreate,
    ProfessorPublic,
    ProfessorUpdate,
    StudentCreate,
    StudentPublic,
    StudentUpdate,
    UserPublic,
)


class UserService:
    def __init__(
        self,
        user_repo: UserRepositoryProtocol,
        audit_repo: AuditLogRepositoryProtocol,
    ) -> None:
        self.user_repo = user_repo
        self.audit_repo = audit_repo

    async def _log_auth_event(
        self,
        user_id: uuid.UUID,
        action: str,
        success: bool,
        ip_address: str | None = None,
        diff: dict | None = None,
    ) -> None:
        await self.audit_repo.create(
            user_id=user_id,
            entity_type="User",
            entity_id=user_id,
            action=action,
            success=success,
            ip_address=ip_address,
            diff=diff,
        )

    async def register_student(self, schema: StudentCreate) -> StudentPublic:
        existing = await self.user_repo.get_by_email(schema.email)
        if existing:
            raise ValueError("Cet email est déjà utilisé")

        # Bug corrigé (500 réel à la création admin, cf. get_by_student_number) —
        # student_number est UNIQUE en base ; sans ce pré-contrôle, une
        # collision remontait comme une IntegrityError brute (500) au lieu
        # d'un ValueError propre (400), même discipline que l'email ci-dessus.
        existing_student_number = await self.user_repo.get_by_student_number(schema.student_number)
        if existing_student_number:
            raise ValueError("Ce numéro d'étudiant est déjà utilisé")

        student = await self.user_repo.create_student(
            email=schema.email,
            hashed_password=hash_password(schema.password),
            first_name=schema.first_name,
            last_name=schema.last_name,
            student_number=schema.student_number,
            group_id=schema.group_id,
            enrollment_year=schema.enrollment_year,
            level=schema.level,
        )
        
        # group_id absent (auto-inscription publique) : le texte libre tapé
        # par l'étudiant est tracé dans l'audit, jamais perdu — c'est ce qui
        # permet à un admin de faire la réassignation manuelle vers le vrai
        # groupe, sans avoir à redemander l'info à l'étudiant.
        diff = (
            {"requested_group_label": schema.requested_group_label}
            if schema.group_id is None and schema.requested_group_label
            else None
        )
        await self._log_auth_event(student.id, "register_student", True, diff=diff)
        return StudentPublic.model_validate(student)

    async def register_professor(self, schema: ProfessorCreate) -> ProfessorPublic:
        existing = await self.user_repo.get_by_email(schema.email)
        if existing:
            raise ValueError("Cet email est déjà utilisé")

        # Même correctif que register_student — employee_number est UNIQUE
        # en base, jamais pré-vérifié avant (cf. get_by_employee_number).
        existing_employee_number = await self.user_repo.get_by_employee_number(schema.employee_number)
        if existing_employee_number:
            raise ValueError("Ce numéro d'employé est déjà utilisé")

        professor = await self.user_repo.create_professor(
            email=schema.email,
            hashed_password=hash_password(schema.password),
            first_name=schema.first_name,
            last_name=schema.last_name,
            department=schema.department,
            title=schema.title,
            employee_number=schema.employee_number,
            office_location=schema.office_location,
            specialty=schema.specialty,
        )

        await self._log_auth_event(professor.id, "register_professor", True)
        return ProfessorPublic.model_validate(professor)

    async def register_admin(self, schema: AdminCreate) -> UserPublic:
        existing = await self.user_repo.get_by_email(schema.email)
        if existing:
            raise ValueError("Cet email est déjà utilisé")

        admin = await self.user_repo.create_admin(
            email=schema.email,
            hashed_password=hash_password(schema.password),
            first_name=schema.first_name,
            last_name=schema.last_name,
        )

        await self._log_auth_event(admin.id, "register_admin", True)
        return UserPublic.model_validate(admin)

    async def get_user_detail(self, user_id: uuid.UUID) -> UserPublic | ProfessorPublic | StudentPublic:
        user = await self.user_repo.get_by_id_with_role_details(user_id)
        if user is None:
            raise ValueError("Utilisateur introuvable")
        if isinstance(user, Student):
            return StudentPublic.model_validate(user)
        if isinstance(user, Professor):
            return ProfessorPublic.model_validate(user)
        return UserPublic.model_validate(user)

    async def _check_email_available(self, email: str, user_id: uuid.UUID) -> None:
        existing = await self.user_repo.get_by_email(email)
        if existing and existing.id != user_id:
            raise ValueError("Cet email est déjà utilisé")

    async def update_student(self, user_id: uuid.UUID, schema: StudentUpdate) -> StudentPublic:
        await self._check_email_available(schema.email, user_id)
        user = await self.user_repo.update(
            user_id,
            email=schema.email,
            first_name=schema.first_name,
            last_name=schema.last_name,
            student_number=schema.student_number,
            group_id=schema.group_id,
            enrollment_year=schema.enrollment_year,
            level=schema.level,
        )
        if user is None:
            raise ValueError("Utilisateur introuvable")
        await self._log_auth_event(user.id, "update_student", True)
        return StudentPublic.model_validate(user)

    async def update_professor(self, user_id: uuid.UUID, schema: ProfessorUpdate) -> ProfessorPublic:
        await self._check_email_available(schema.email, user_id)
        user = await self.user_repo.update(
            user_id,
            email=schema.email,
            first_name=schema.first_name,
            last_name=schema.last_name,
            department=schema.department,
            title=schema.title,
            employee_number=schema.employee_number,
            office_location=schema.office_location,
            specialty=schema.specialty,
        )
        if user is None:
            raise ValueError("Utilisateur introuvable")
        await self._log_auth_event(user.id, "update_professor", True)
        return ProfessorPublic.model_validate(user)

    async def update_admin(self, user_id: uuid.UUID, schema: AdminUpdate) -> UserPublic:
        await self._check_email_available(schema.email, user_id)
        user = await self.user_repo.update(
            user_id,
            email=schema.email,
            first_name=schema.first_name,
            last_name=schema.last_name,
        )
        if user is None:
            raise ValueError("Utilisateur introuvable")
        await self._log_auth_event(user.id, "update_admin", True)
        return UserPublic.model_validate(user)

    async def authenticate(self, request: LoginRequest, ip_address: str | None = None) -> User:
        user = await self.user_repo.get_by_email(request.email)
        if not user:
            raise ValueError("Identifiants invalides")

        # Vérification du mot de passe D'ABORD (avant is_active) — ne jamais
        # révéler qu'un compte est désactivé à quelqu'un qui n'a pas le bon
        # mot de passe, même raisonnement que le message générique
        # "Identifiants invalides" déjà en place.
        if not verify_password(request.password, user.hashed_password):
            await self._log_auth_event(user.id, "login", False, ip_address)
            raise ValueError("Identifiants invalides")

        if not user.is_active:
            await self._log_auth_event(user.id, "login", False, ip_address)
            raise ValueError("Compte désactivé")

        # Update last login
        await self.user_repo.update(user.id, totp_last_used_at=datetime.now(timezone.utc) if user.totp_enabled else None)
        await self._log_auth_event(user.id, "login", True, ip_address)
        
        return user

    async def authenticate_with_google(self, google_email: str, ip_address: str | None = None) -> User:
        """
        "Se connecter avec Google" (cf. mémoire de session) — l'email a déjà
        été vérifié comme réellement authentifié par Google (app/auth/
        google_oauth.py) AVANT cet appel ; ce qui reste à vérifier ici est
        IDENTIQUE à authenticate() sauf le mot de passe (jamais requis
        Google) : décision d'architecture "liaison à un compte déjà
        existant seulement" — aucune création de compte via ce chemin,
        contrairement à register_student/register_professor. Un email
        Google sans compte existant sur la plateforme est refusé — jamais
        une inscription implicite.
        """
        user = await self.user_repo.get_by_email(google_email)
        if not user:
            raise ValueError(
                "Aucun compte n'est associé à cet email. Contactez un administrateur "
                "pour créer votre compte avant d'utiliser la connexion Google."
            )

        if not user.is_active:
            await self._log_auth_event(user.id, "login_google", False, ip_address)
            raise ValueError("Compte désactivé")

        await self.user_repo.update(user.id, totp_last_used_at=datetime.now(timezone.utc) if user.totp_enabled else None)
        await self._log_auth_event(user.id, "login_google", True, ip_address)

        return user

    def generate_tokens(self, user: User) -> dict[str, str]:
        return {
            "access_token": create_access_token(str(user.id), user.role.value),
            "refresh_token": create_refresh_token(str(user.id), user.role.value),
        }


    # MFA Functions
    async def setup_mfa(self, user: User) -> dict[str, str]:
        if user.totp_enabled:
            raise ValueError("MFA est déjà activé pour cet utilisateur")
            
        secret = pyotp.random_base32()
        await self.user_repo.update(user.id, totp_secret=secret)
        
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=user.email, issuer_name="EducationalPlatform")
        
        return {"secret": secret, "qr_code_uri": uri}

    async def enable_mfa(self, user: User, code: str) -> None:
        if user.totp_enabled:
            raise ValueError("MFA est déjà activé")
        if not user.totp_secret:
            raise ValueError("MFA n'a pas été initialisé (appelez /setup d'abord)")
            
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code):
            raise ValueError("Code TOTP invalide")
            
        await self.user_repo.update(
            user.id,
            totp_enabled=True,
            totp_verified_at=datetime.now(timezone.utc)
        )
        await self._log_auth_event(user.id, "mfa_enable", True)

    async def verify_mfa(self, user: User, code: str) -> None:
        if not user.totp_enabled or not user.totp_secret:
            raise ValueError("MFA n'est pas activé pour cet utilisateur")
            
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code):
            await self._log_auth_event(user.id, "mfa_verify", False)
            raise ValueError("Code TOTP invalide")
            
        await self.user_repo.update(user.id, totp_last_used_at=datetime.now(timezone.utc))
        await self._log_auth_event(user.id, "mfa_verify", True)

    async def disable_mfa(self, user: User, password: str) -> None:
        if not verify_password(password, user.hashed_password):
            await self._log_auth_event(user.id, "mfa_disable", False)
            raise ValueError("Mot de passe incorrect")
            
        await self.user_repo.update(
            user.id,
            totp_enabled=False,
            totp_secret=None,
            totp_verified_at=None,
        )
        await self._log_auth_event(user.id, "mfa_disable", True)

    # --- Gestion admin des comptes ---

    async def list_users(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE, role: UserRole | None = None,
    ) -> CursorPage[User]:
        return await self.user_repo.list_users(cursor=cursor, limit=limit, role=role)

    async def deactivate_account(self, target_user_id: uuid.UUID, acting_admin_id: uuid.UUID) -> User:
        """
        Garde-fou explicite (contrainte ticket) : un admin ne peut jamais se
        désactiver lui-même par erreur — vérifié AVANT toute lecture du
        compte cible, jamais après (pas de fenêtre où l'admin serait déjà
        désactivé si une erreur survenait entre-temps).
        """
        if target_user_id == acting_admin_id:
            raise ValueError("Un administrateur ne peut pas désactiver son propre compte")

        user = await self.user_repo.update(target_user_id, is_active=False)
        if user is None:
            raise ValueError("Utilisateur introuvable")

        await self._log_auth_event(target_user_id, "admin_deactivate_account", True)
        return user

    async def reactivate_account(self, target_user_id: uuid.UUID) -> User:
        user = await self.user_repo.update(target_user_id, is_active=True)
        if user is None:
            raise ValueError("Utilisateur introuvable")

        await self._log_auth_event(target_user_id, "admin_reactivate_account", True)
        return user

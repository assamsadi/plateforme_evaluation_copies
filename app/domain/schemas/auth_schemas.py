"""
Schemas Pydantic pour l'authentification : login, tokens, création de
compte par rôle (miroir de l'héritage User -> Student/Professor/Admin
en base — validation stricte, chaque rôle exige ses propres champs).
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.models.identity.user import AcademicStatus, UserRole


# --- Login ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    """Jeton d'identité (ID token JWT) renvoyé par Google Identity Services
    côté frontend (google.accounts.id.initialize/callback) — jamais un
    access_token OAuth classique, jamais l'email en clair (usurpable) :
    seul ce jeton signé par Google, vérifié côté serveur (app/auth/
    google_oauth.py), fait foi de l'identité réelle."""
    credential: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserPublic"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# --- Création de compte, un schema par rôle ---

class UserCreateBase(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    first_name: str
    last_name: str


class StudentCreate(UserCreateBase):
    student_number: str
    # None sur l'auto-inscription publique (aucun endpoint anonyme ne permet
    # de choisir un vrai groupe) — le repository substitue alors le groupe
    # "non assigné" (cf. UNASSIGNED_GROUP_LABEL dans user_repository.py).
    # Toujours fourni sur la création admin (StudentCreate y est réutilisé
    # tel quel), qui elle connaît le vrai groupe.
    group_id: uuid.UUID | None = None
    # Nom/code de groupe tapé librement par l'étudiant à l'inscription
    # publique — jamais un vrai group_id, juste un indice pour l'admin qui
    # réassignera manuellement (cf. diff de l'événement d'audit
    # "register_student"). Absent sur la création admin.
    requested_group_label: str | None = None
    enrollment_year: int
    level: str


class ProfessorCreate(UserCreateBase):
    department: str
    title: str
    employee_number: str
    office_location: str | None = None
    specialty: str | None = None


class AdminCreate(UserCreateBase):
    pass


# --- Modification de compte, un schema par rôle (miroir des *Create,
# sans le mot de passe — changer le mot de passe est un flux séparé,
# pas une simple édition de profil) ---

class UserUpdateBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str


class StudentUpdate(UserUpdateBase):
    student_number: str
    group_id: uuid.UUID
    enrollment_year: int
    level: str


class ProfessorUpdate(UserUpdateBase):
    department: str
    title: str
    employee_number: str
    office_location: str | None = None
    specialty: str | None = None


class AdminUpdate(UserUpdateBase):
    pass


# --- Lecture (réponse API, jamais de hashed_password exposé) ---

class UserPublic(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: UserRole
    first_name: str
    last_name: str
    is_active: bool

    model_config = {"from_attributes": True}  # permet .model_validate(orm_instance)


class StudentPublic(UserPublic):
    student_number: str
    group_id: uuid.UUID
    enrollment_year: int
    academic_status: AcademicStatus
    level: str


class ProfessorPublic(UserPublic):
    department: str
    title: str
    employee_number: str
    office_location: str | None
    specialty: str | None


TokenResponse.model_rebuild()

# --- Multi-Factor Authentication (TOTP) ---

class MFASetupResponse(BaseModel):
    secret: str
    qr_code_uri: str


class MFAEnableRequest(BaseModel):
    code: str = Field(
        min_length=6,
        max_length=6,
        description="Code TOTP à 6 chiffres"
    )


class MFAVerifyRequest(BaseModel):
    code: str = Field(
        min_length=6,
        max_length=6,
        description="Code TOTP à 6 chiffres"
    )


class MFAStatusResponse(BaseModel):
    enabled: bool
    verified_at: datetime | None
    last_used_at: datetime | None


class MFADisableRequest(BaseModel):
    password: str
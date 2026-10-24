import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, get_user_service, require_role
from app.auth.dependencies import oauth2_scheme
from app.auth.google_oauth import (
    GoogleAuthDisabledError,
    InvalidGoogleCredentialError,
    verify_google_id_token,
)
from app.auth.jwt_handler import TokenType, decode_token, revoke_refresh_token, TokenError
from app.domain.models.identity.user import User, UserRole
from app.domain.schemas.auth_schemas import (
    GoogleLoginRequest,
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    StudentCreate,
    StudentPublic,
    MFASetupResponse,
    MFAEnableRequest,
    MFAVerifyRequest,
    MFAStatusResponse,
    MFADisableRequest,
)
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register/student", response_model=StudentPublic, status_code=status.HTTP_201_CREATED)
async def register_student(
    schema: StudentCreate,
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        return await user_service.register_student(schema)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
async def login(
    request: LoginRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        user = await user_service.authenticate(request)

        if user.totp_enabled:
            # Generate a transient MFA token
            from app.auth.jwt_handler import create_mfa_token
            mfa_token = create_mfa_token(str(user.id), user.role.value)
            return {"mfa_required": True, "mfa_token": mfa_token}

        tokens = user_service.generate_tokens(user)
        return {
            **tokens,
            "token_type": "bearer",
            "user": user,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login/google")
async def login_google(
    request: GoogleLoginRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    "Se connecter avec Google" (cf. mémoire de session) — même forme de
    réponse que /login (mfa_required le cas échéant, sinon les jetons),
    pour que le frontend réutilise EXACTEMENT le même traitement de
    réponse que la connexion classique. Ne crée jamais de compte : un
    email Google sans compte existant est refusé (UserService.
    authenticate_with_google).
    """
    try:
        email = verify_google_id_token(request.credential)
    except GoogleAuthDisabledError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except InvalidGoogleCredentialError as e:
        raise HTTPException(status_code=401, detail=str(e))

    try:
        user = await user_service.authenticate_with_google(email)

        if user.totp_enabled:
            from app.auth.jwt_handler import create_mfa_token
            mfa_token = create_mfa_token(str(user.id), user.role.value)
            return {"mfa_required": True, "mfa_token": mfa_token}

        tokens = user_service.generate_tokens(user)
        return {
            **tokens,
            "token_type": "bearer",
            "user": user,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login/verify-mfa")
async def verify_mfa_login(
    request: MFAVerifyRequest,
    mfa_token: str,
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        payload = await decode_token(mfa_token, expected_type=TokenType.ACCESS)
        if not payload.get("mfa_pending"):
            raise HTTPException(status_code=400, detail="Token n'est pas un jeton MFA pending")

        user_id = uuid.UUID(payload["sub"])
        user = await user_service.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Utilisateur invalide")

        await user_service.verify_mfa(user, request.code)

        tokens = user_service.generate_tokens(user)
        return {
            **tokens,
            "token_type": "bearer",
            "user": user,
        }
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        # Decode and verify it's a refresh token
        payload = await decode_token(request.refresh_token, expected_type=TokenType.REFRESH)
        user_id = uuid.UUID(payload["sub"])

        # Load user
        user = await user_service.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Utilisateur invalide")

        # Create new tokens
        tokens = user_service.generate_tokens(user)

        # Revoke the old refresh token (blacklist its JTI)
        from datetime import datetime, timezone
        jti = payload["jti"]
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expires_in = exp - datetime.now(timezone.utc)
        await revoke_refresh_token(jti, expires_in)

        return {
            **tokens,
            "token_type": "bearer",
            "user": user,
        }
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/logout")
async def logout(
    request: RefreshTokenRequest,
    current_user: Annotated[User, Depends(get_current_user)],
):
    try:
        payload = await decode_token(request.refresh_token, expected_type=TokenType.REFRESH)

        from datetime import datetime, timezone
        jti = payload["jti"]
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expires_in = exp - datetime.now(timezone.utc)

        await revoke_refresh_token(jti, expires_in)
        return {"detail": "Déconnecté avec succès"}
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))


# MFA Endpoints

@router.post("/mfa/setup", response_model=MFASetupResponse)
async def mfa_setup(
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        return await user_service.setup_mfa(current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mfa/enable")
async def mfa_enable(
    request: MFAEnableRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        await user_service.enable_mfa(current_user, request.code)
        return {"detail": "MFA activé avec succès"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/mfa/disable")
async def mfa_disable(
    request: MFADisableRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        await user_service.disable_mfa(current_user, request.password)
        return {"detail": "MFA désactivé avec succès"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@router.get("/mfa/status", response_model=MFAStatusResponse)
async def mfa_status(
    current_user: Annotated[User, Depends(get_current_user)],
):
    return {
        "enabled": current_user.totp_enabled,
        "verified_at": current_user.totp_verified_at,
        "last_used_at": current_user.totp_last_used_at,
    }

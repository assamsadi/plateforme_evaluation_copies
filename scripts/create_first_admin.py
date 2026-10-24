import asyncio
import sys
from getpass import getpass

from sqlalchemy import select

from app.core.database import async_session_maker
from app.domain.models.identity.user import Admin
from app.domain.repositories.audit_log_repository import SQLAlchemyAuditLogRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.schemas.auth_schemas import AdminCreate
from app.services.user_service import UserService


async def main():
    async with async_session_maker() as session:
        # Check if an admin already exists
        result = await session.execute(select(Admin).limit(1))
        existing_admin = result.scalar_one_or_none()
        
        if existing_admin:
            print("Erreur: Un administrateur existe déjà dans la base de données.")
            print("Ce script ne peut être utilisé que pour le bootstrapping initial.")
            sys.exit(1)

        print("=== Création du premier administrateur ===")
        email = input("Email: ").strip()
        first_name = input("Prénom: ").strip()
        last_name = input("Nom: ").strip()
        
        password = getpass("Mot de passe (minimum 8 caractères): ")
        password_confirm = getpass("Confirmez le mot de passe: ")
        
        if password != password_confirm:
            print("Erreur: Les mots de passe ne correspondent pas.")
            sys.exit(1)
            
        if len(password) < 8:
            print("Erreur: Le mot de passe doit faire au moins 8 caractères.")
            sys.exit(1)

        try:
            schema = AdminCreate(
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
            )
            service = UserService(
                user_repo=SQLAlchemyUserRepository(session),
                audit_repo=SQLAlchemyAuditLogRepository(session),
            )
            admin = await service.register_admin(schema)
            await session.commit()
            print(f"Succès: Administrateur {admin.email} créé avec succès. ID: {admin.id}")
        except Exception as e:
            await session.rollback()
            print(f"Erreur lors de la création: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

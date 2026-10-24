"""
Crée (si absent) le programme + groupe sentinelle "non assigné" utilisé par
l'auto-inscription publique des étudiants (POST /auth/register/student)
quand aucun group_id réel n'est fourni — cf. UNASSIGNED_PROGRAM_CODE dans
app/domain/repositories/user_repository.py.

Idempotent : relancer ce script ne crée pas de doublon, contrairement à
create_first_admin.py qui lui refuse tout re-run.
"""
import asyncio

from sqlalchemy import select

from app.core.database import async_session_maker
from app.domain.models.academic.group import Group
from app.domain.models.academic.program import Program
from app.domain.repositories.user_repository import (
    UNASSIGNED_GROUP_LABEL,
    UNASSIGNED_PROGRAM_CODE,
)


async def main():
    async with async_session_maker() as session:
        result = await session.execute(
            select(Program).where(Program.code == UNASSIGNED_PROGRAM_CODE)
        )
        program = result.scalar_one_or_none()

        if program is None:
            program = Program(name="Non assigné", code=UNASSIGNED_PROGRAM_CODE)
            session.add(program)
            await session.flush()
            print(f"Programme sentinelle créé : {program.id}")
        else:
            print(f"Programme sentinelle déjà présent : {program.id}")

        result = await session.execute(
            select(Group).where(
                Group.program_id == program.id, Group.label == UNASSIGNED_GROUP_LABEL
            )
        )
        group = result.scalar_one_or_none()

        if group is None:
            group = Group(
                program_id=program.id,
                label=UNASSIGNED_GROUP_LABEL,
                academic_year="N/A",
            )
            session.add(group)
            await session.flush()
            print(f"Groupe sentinelle créé : {group.id}")
        else:
            print(f"Groupe sentinelle déjà présent : {group.id}")

        await session.commit()
        print("OK — l'inscription publique peut maintenant fonctionner sans group_id.")


if __name__ == "__main__":
    asyncio.run(main())

"""
Tests du ModuleRepository — couvre toutes les méthodes publiques :
- create (nominal, contrainte d'unicité code, contrainte program+name)
- get_by_id (nominal, non trouvé)
- get_by_code (nominal, non trouvé)
- get_by_program_and_name (nominal, non trouvé)
- list_page (nominal, vide, pagination)
- list_by_program (nominal, filtre par program, pagination)
- delete (nominal, non trouvé)
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.module import Module
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository


@pytest.fixture
async def program(db_session):
    """Crée un Program de référence pour les tests de Module."""
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Test Program {uuid.uuid4().hex[:8]}", code=f"TP{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def other_program(db_session):
    """Crée un second Program pour tester le filtrage par program."""
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Other Program {uuid.uuid4().hex[:8]}", code=f"OP{uuid.uuid4().hex[:6]}")


@pytest.mark.anyio
class TestModuleRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session, program):
        """Création nominale : vérifie que le module est persisté avec les bons champs."""
        repo = SQLAlchemyModuleRepository(db_session)
        module = await repo.create(program_id=program.id, name="Analyse Numérique", code="AN")

        assert module.id is not None
        assert module.program_id == program.id
        assert module.name == "Analyse Numérique"
        assert module.code == "AN"
        assert module.created_at is not None

    async def test_create_duplicate_code_raises_integrity_error(self, db_session, program):
        """Contrainte d'unicité sur code : un deuxième module avec le même code lève IntegrityError."""
        repo = SQLAlchemyModuleRepository(db_session)
        await repo.create(program_id=program.id, name="Module A", code="DUP")

        with pytest.raises(IntegrityError):
            await repo.create(program_id=program.id, name="Module B", code="DUP")
        await db_session.rollback()

    async def test_create_duplicate_program_name_raises_integrity_error(self, db_session, program):
        """Contrainte d'unicité (program_id, name) : même nom dans le même program lève IntegrityError."""
        repo = SQLAlchemyModuleRepository(db_session)
        await repo.create(program_id=program.id, name="Same Name", code="SN1")

        with pytest.raises(IntegrityError):
            await repo.create(program_id=program.id, name="Same Name", code="SN2")
        await db_session.rollback()

    async def test_create_same_name_different_program_ok(self, db_session, program, other_program):
        """Le même nom dans deux programs différents est autorisé (contrainte sur program+name)."""
        repo = SQLAlchemyModuleRepository(db_session)
        m1 = await repo.create(program_id=program.id, name="Shared Name", code="SH1")
        m2 = await repo.create(program_id=other_program.id, name="Shared Name", code="SH2")

        assert m1.id != m2.id
        assert m1.name == m2.name == "Shared Name"


@pytest.mark.anyio
class TestModuleRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session, program):
        """get_by_id retourne le module quand il existe."""
        repo = SQLAlchemyModuleRepository(db_session)
        created = await repo.create(program_id=program.id, name="Physique", code="PHY")

        found = await repo.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.name == "Physique"
        assert found.code == "PHY"
        assert found.program_id == program.id

    async def test_get_by_id_not_found_returns_none(self, db_session):
        """get_by_id retourne None quand le module n'existe pas."""
        repo = SQLAlchemyModuleRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestModuleRepositoryGetByCode:
    """Tests de la méthode get_by_code()."""

    async def test_get_by_code_found(self, db_session, program):
        """get_by_code retourne le module quand le code existe."""
        repo = SQLAlchemyModuleRepository(db_session)
        await repo.create(program_id=program.id, name="Chimie", code="CHM")

        found = await repo.get_by_code("CHM")

        assert found is not None
        assert found.name == "Chimie"
        assert found.code == "CHM"

    async def test_get_by_code_not_found_returns_none(self, db_session):
        """get_by_code retourne None quand le code n'existe pas."""
        repo = SQLAlchemyModuleRepository(db_session)

        found = await repo.get_by_code("NONEXISTENT")

        assert found is None


@pytest.mark.anyio
class TestModuleRepositoryGetByProgramAndName:
    """Tests de la méthode get_by_program_and_name()."""

    async def test_get_by_program_and_name_found(self, db_session, program):
        """get_by_program_and_name retourne le module quand (program_id, name) correspond."""
        repo = SQLAlchemyModuleRepository(db_session)
        await repo.create(program_id=program.id, name="Algorithmique", code="ALG")

        found = await repo.get_by_program_and_name(program.id, "Algorithmique")

        assert found is not None
        assert found.name == "Algorithmique"
        assert found.program_id == program.id

    async def test_get_by_program_and_name_not_found_returns_none(self, db_session, program):
        """get_by_program_and_name retourne None quand la combinaison n'existe pas."""
        repo = SQLAlchemyModuleRepository(db_session)

        found = await repo.get_by_program_and_name(program.id, "Nonexistent Module")

        assert found is None

    async def test_get_by_program_and_name_different_program(self, db_session, program, other_program):
        """get_by_program_and_name ne retourne pas un module d'un autre program."""
        repo = SQLAlchemyModuleRepository(db_session)
        await repo.create(program_id=other_program.id, name="Unique Module", code="UM1")

        found = await repo.get_by_program_and_name(program.id, "Unique Module")

        assert found is None


@pytest.mark.anyio
class TestModuleRepositoryListPage:
    """Tests de la méthode list_page() avec pagination par curseur."""

    async def test_list_page_empty(self, db_session):
        """list_page sur une table vide retourne une page vide."""
        repo = SQLAlchemyModuleRepository(db_session)

        page = await repo.list_page()

        assert page.items == []
        assert page.next_cursor is None
        assert page.has_more is False

    async def test_list_page_nominal(self, db_session, program):
        """list_page retourne les modules triés par (created_at, id)."""
        repo = SQLAlchemyModuleRepository(db_session)
        m1 = await repo.create(program_id=program.id, name="Module 1", code="M1")
        m2 = await repo.create(program_id=program.id, name="Module 2", code="M2")
        m3 = await repo.create(program_id=program.id, name="Module 3", code="M3")

        page = await repo.list_page()

        assert len(page.items) == 3
        expected = sorted([m1, m2, m3], key=lambda m: (m.created_at, m.id))
        assert [m.id for m in page.items] == [m.id for m in expected]
        assert page.has_more is False

    async def test_list_page_pagination_has_more(self, db_session, program):
        """list_page avec limit < total : has_more=True et next_cursor défini."""
        repo = SQLAlchemyModuleRepository(db_session)
        for i in range(5):
            await repo.create(program_id=program.id, name=f"Mod {i}", code=f"MP{i}")

        page = await repo.list_page(limit=2)

        assert len(page.items) == 2
        assert page.has_more is True
        assert page.next_cursor is not None

    async def test_list_page_pagination_next_page(self, db_session, program):
        """list_page avec curseur : la deuxième page retourne les éléments suivants."""
        repo = SQLAlchemyModuleRepository(db_session)
        for i in range(5):
            await repo.create(program_id=program.id, name=f"Cursor {i}", code=f"CR{i}")

        first_page = await repo.list_page(limit=2)
        assert first_page.has_more is True

        second_page = await repo.list_page(cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id
        assert second_page.items[0].id != first_page.items[1].id


@pytest.mark.anyio
class TestModuleRepositoryListByProgram:
    """Tests de la méthode list_by_program() avec filtre par program et pagination."""

    async def test_list_by_program_nominal(self, db_session, program, other_program):
        """list_by_program retourne uniquement les modules du program spécifié."""
        repo = SQLAlchemyModuleRepository(db_session)
        m1 = await repo.create(program_id=program.id, name="Prog Module 1", code="PM1")
        m2 = await repo.create(program_id=program.id, name="Prog Module 2", code="PM2")
        m3 = await repo.create(program_id=other_program.id, name="Other Module", code="OM1")

        page = await repo.list_by_program(program.id)

        assert len(page.items) == 2
        assert all(m.program_id == program.id for m in page.items)
        expected = sorted([m1, m2], key=lambda m: (m.created_at, m.id))
        assert [m.id for m in page.items] == [m.id for m in expected]

    async def test_list_by_program_empty(self, db_session, program):
        """list_by_program sur un program sans modules retourne une page vide."""
        repo = SQLAlchemyModuleRepository(db_session)

        page = await repo.list_by_program(program.id)

        assert page.items == []
        assert page.has_more is False

    async def test_list_by_program_pagination(self, db_session, program):
        """list_by_program avec pagination : has_more et next_cursor fonctionnent."""
        repo = SQLAlchemyModuleRepository(db_session)
        for i in range(5):
            await repo.create(program_id=program.id, name=f"Paginated {i}", code=f"PG{i}")

        first_page = await repo.list_by_program(program.id, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_by_program(program.id, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id


@pytest.mark.anyio
class TestModuleRepositoryDelete:
    """Tests de la méthode delete()."""

    async def test_delete_nominal(self, db_session, program):
        """delete supprime le module et retourne True."""
        repo = SQLAlchemyModuleRepository(db_session)
        created = await repo.create(program_id=program.id, name="To Delete", code="DEL")

        result = await repo.delete(created.id)

        assert result is True
        found = await repo.get_by_id(created.id)
        assert found is None

    async def test_delete_not_found_returns_false(self, db_session):
        """delete sur un ID inexistant retourne False."""
        repo = SQLAlchemyModuleRepository(db_session)

        result = await repo.delete(uuid.uuid4())

        assert result is False
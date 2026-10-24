"""
Tests du GroupRepository — couvre toutes les méthodes publiques :
- create (nominal, contrainte d'unicité program+label)
- get_by_id (nominal, non trouvé)
- get_by_program_and_label (nominal, non trouvé, cross-program)
- list_page (nominal, vide, pagination)
- list_by_program (nominal, filtre par program, pagination)
- delete (nominal, non trouvé)
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.group import Group
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository


@pytest.fixture
async def program(db_session):
    """Crée un Program de référence pour les tests de Group."""
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Test Program {uuid.uuid4().hex[:8]}", code=f"TP{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def other_program(db_session):
    """Crée un second Program pour tester le filtrage par program."""
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Other Program {uuid.uuid4().hex[:8]}", code=f"OP{uuid.uuid4().hex[:6]}")


@pytest.mark.anyio
class TestGroupRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session, program):
        """Création nominale : vérifie que le group est persisté avec les bons champs."""
        repo = SQLAlchemyGroupRepository(db_session)
        group = await repo.create(program_id=program.id, label="TD1", academic_year="2025-2026")

        assert group.id is not None
        assert group.program_id == program.id
        assert group.label == "TD1"
        assert group.academic_year == "2025-2026"
        assert group.created_at is not None

    async def test_create_duplicate_program_label_raises_integrity_error(self, db_session, program):
        """Contrainte d'unicité (program_id, label) : même label dans le même program lève IntegrityError."""
        repo = SQLAlchemyGroupRepository(db_session)
        await repo.create(program_id=program.id, label="TD1", academic_year="2025-2026")

        with pytest.raises(IntegrityError):
            await repo.create(program_id=program.id, label="TD1", academic_year="2026-2027")
        await db_session.rollback()

    async def test_create_same_label_different_program_ok(self, db_session, program, other_program):
        """Le même label dans deux programs différents est autorisé."""
        repo = SQLAlchemyGroupRepository(db_session)
        g1 = await repo.create(program_id=program.id, label="TD1", academic_year="2025-2026")
        g2 = await repo.create(program_id=other_program.id, label="TD1", academic_year="2025-2026")

        assert g1.id != g2.id
        assert g1.label == g2.label == "TD1"


@pytest.mark.anyio
class TestGroupRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session, program):
        """get_by_id retourne le group quand il existe."""
        repo = SQLAlchemyGroupRepository(db_session)
        created = await repo.create(program_id=program.id, label="TD2", academic_year="2025-2026")

        found = await repo.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.label == "TD2"
        assert found.academic_year == "2025-2026"
        assert found.program_id == program.id

    async def test_get_by_id_not_found_returns_none(self, db_session):
        """get_by_id retourne None quand le group n'existe pas."""
        repo = SQLAlchemyGroupRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestGroupRepositoryGetByProgramAndLabel:
    """Tests de la méthode get_by_program_and_label()."""

    async def test_get_by_program_and_label_found(self, db_session, program):
        """get_by_program_and_label retourne le group quand (program_id, label) correspond."""
        repo = SQLAlchemyGroupRepository(db_session)
        await repo.create(program_id=program.id, label="TD3", academic_year="2025-2026")

        found = await repo.get_by_program_and_label(program.id, "TD3")

        assert found is not None
        assert found.label == "TD3"
        assert found.program_id == program.id

    async def test_get_by_program_and_label_not_found_returns_none(self, db_session, program):
        """get_by_program_and_label retourne None quand la combinaison n'existe pas."""
        repo = SQLAlchemyGroupRepository(db_session)

        found = await repo.get_by_program_and_label(program.id, "Nonexistent")

        assert found is None

    async def test_get_by_program_and_label_different_program(self, db_session, program, other_program):
        """get_by_program_and_label ne retourne pas un group d'un autre program."""
        repo = SQLAlchemyGroupRepository(db_session)
        await repo.create(program_id=other_program.id, label="TD4", academic_year="2025-2026")

        found = await repo.get_by_program_and_label(program.id, "TD4")

        assert found is None


@pytest.mark.anyio
class TestGroupRepositoryListPage:
    """Tests de la méthode list_page() avec pagination par curseur."""

    async def test_list_page_empty(self, db_session):
        """list_page sur une table vide retourne une page vide."""
        repo = SQLAlchemyGroupRepository(db_session)

        page = await repo.list_page()

        assert page.items == []
        assert page.next_cursor is None
        assert page.has_more is False

    async def test_list_page_nominal(self, db_session, program):
        """list_page retourne les groups triés par (created_at, id)."""
        repo = SQLAlchemyGroupRepository(db_session)
        g1 = await repo.create(program_id=program.id, label="G1", academic_year="2025")
        g2 = await repo.create(program_id=program.id, label="G2", academic_year="2025")
        g3 = await repo.create(program_id=program.id, label="G3", academic_year="2025")

        page = await repo.list_page()

        assert len(page.items) == 3
        expected = sorted([g1, g2, g3], key=lambda g: (g.created_at, g.id))
        assert [g.id for g in page.items] == [g.id for g in expected]
        assert page.has_more is False

    async def test_list_page_pagination_has_more(self, db_session, program):
        """list_page avec limit < total : has_more=True et next_cursor défini."""
        repo = SQLAlchemyGroupRepository(db_session)
        for i in range(5):
            await repo.create(program_id=program.id, label=f"P{i}", academic_year="2025")

        page = await repo.list_page(limit=2)

        assert len(page.items) == 2
        assert page.has_more is True
        assert page.next_cursor is not None

    async def test_list_page_pagination_next_page(self, db_session, program):
        """list_page avec curseur : la deuxième page retourne les éléments suivants."""
        repo = SQLAlchemyGroupRepository(db_session)
        for i in range(5):
            await repo.create(program_id=program.id, label=f"C{i}", academic_year="2025")

        first_page = await repo.list_page(limit=2)
        assert first_page.has_more is True

        second_page = await repo.list_page(cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id
        assert second_page.items[0].id != first_page.items[1].id


@pytest.mark.anyio
class TestGroupRepositoryListByProgram:
    """Tests de la méthode list_by_program() avec filtre par program et pagination."""

    async def test_list_by_program_nominal(self, db_session, program, other_program):
        """list_by_program retourne uniquement les groups du program spécifié."""
        repo = SQLAlchemyGroupRepository(db_session)
        g1 = await repo.create(program_id=program.id, label="LP1", academic_year="2025")
        g2 = await repo.create(program_id=program.id, label="LP2", academic_year="2025")
        g3 = await repo.create(program_id=other_program.id, label="OP1", academic_year="2025")

        page = await repo.list_by_program(program.id)

        assert len(page.items) == 2
        assert all(g.program_id == program.id for g in page.items)
        expected = sorted([g1, g2], key=lambda g: (g.created_at, g.id))
        assert [g.id for g in page.items] == [g.id for g in expected]

    async def test_list_by_program_empty(self, db_session, program):
        """list_by_program sur un program sans groups retourne une page vide."""
        repo = SQLAlchemyGroupRepository(db_session)

        page = await repo.list_by_program(program.id)

        assert page.items == []
        assert page.has_more is False

    async def test_list_by_program_pagination(self, db_session, program):
        """list_by_program avec pagination : has_more et next_cursor fonctionnent."""
        repo = SQLAlchemyGroupRepository(db_session)
        for i in range(5):
            await repo.create(program_id=program.id, label=f"PG{i}", academic_year="2025")

        first_page = await repo.list_by_program(program.id, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_by_program(program.id, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id


@pytest.mark.anyio
class TestGroupRepositoryDelete:
    """Tests de la méthode delete()."""

    async def test_delete_nominal(self, db_session, program):
        """delete supprime le group et retourne True."""
        repo = SQLAlchemyGroupRepository(db_session)
        created = await repo.create(program_id=program.id, label="DEL", academic_year="2025")

        result = await repo.delete(created.id)

        assert result is True
        found = await repo.get_by_id(created.id)
        assert found is None

    async def test_delete_not_found_returns_false(self, db_session):
        """delete sur un ID inexistant retourne False."""
        repo = SQLAlchemyGroupRepository(db_session)

        result = await repo.delete(uuid.uuid4())

        assert result is False
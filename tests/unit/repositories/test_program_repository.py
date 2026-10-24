"""
Tests du ProgramRepository — couvre toutes les méthodes publiques :
- create (nominal, contrainte d'unicité name/code)
- get_by_id (nominal, non trouvé)
- get_by_code (nominal, non trouvé)
- list_page (nominal, vide, pagination curseur, has_more)
- update (nominal, non trouvé)
- delete (nominal, non trouvé)
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.program import Program
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.pagination import DEFAULT_PAGE_SIZE


@pytest.mark.anyio
class TestProgramRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session):
        """Création nominale : vérifie que le program est persisté avec les bons champs."""
        repo = SQLAlchemyProgramRepository(db_session)
        program = await repo.create(name="Génie Civil", code="GC")

        assert program.id is not None
        assert program.name == "Génie Civil"
        assert program.code == "GC"
        assert program.created_at is not None
        assert program.updated_at is not None

    async def test_create_duplicate_name_raises_integrity_error(self, db_session):
        """Contrainte d'unicité sur name : une deuxième création avec le même nom lève IntegrityError."""
        repo = SQLAlchemyProgramRepository(db_session)
        await repo.create(name="Informatique", code="INFO")

        with pytest.raises(IntegrityError):
            await repo.create(name="Informatique", code="INF2")
        await db_session.rollback()

    async def test_create_duplicate_code_raises_integrity_error(self, db_session):
        """Contrainte d'unicité sur code : un deuxième program avec le même code lève IntegrityError."""
        repo = SQLAlchemyProgramRepository(db_session)
        await repo.create(name="Mathématiques", code="MATH")

        with pytest.raises(IntegrityError):
            await repo.create(name="Mathématiques Appliquées", code="MATH")
        await db_session.rollback()


@pytest.mark.anyio
class TestProgramRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session):
        """get_by_id retourne le program quand il existe."""
        repo = SQLAlchemyProgramRepository(db_session)
        created = await repo.create(name="Physique", code="PHY")

        found = await repo.get_by_id(created.id)

        assert found is not None
        assert found.id == created.id
        assert found.name == "Physique"
        assert found.code == "PHY"

    async def test_get_by_id_not_found_returns_none(self, db_session):
        """get_by_id retourne None quand le program n'existe pas."""
        repo = SQLAlchemyProgramRepository(db_session)
        random_id = uuid.uuid4()

        found = await repo.get_by_id(random_id)

        assert found is None


@pytest.mark.anyio
class TestProgramRepositoryGetByCode:
    """Tests de la méthode get_by_code()."""

    async def test_get_by_code_found(self, db_session):
        """get_by_code retourne le program quand le code existe."""
        repo = SQLAlchemyProgramRepository(db_session)
        await repo.create(name="Chimie", code="CHIM")

        found = await repo.get_by_code("CHIM")

        assert found is not None
        assert found.name == "Chimie"
        assert found.code == "CHIM"

    async def test_get_by_code_not_found_returns_none(self, db_session):
        """get_by_code retourne None quand le code n'existe pas."""
        repo = SQLAlchemyProgramRepository(db_session)

        found = await repo.get_by_code("NONEXISTENT")

        assert found is None


@pytest.mark.anyio
class TestProgramRepositoryListPage:
    """Tests de la méthode list_page() avec pagination par curseur."""

    async def test_list_page_empty(self, db_session):
        """list_page sur une table vide retourne une page vide sans next_cursor."""
        repo = SQLAlchemyProgramRepository(db_session)

        page = await repo.list_page()

        assert page.items == []
        assert page.next_cursor is None
        assert page.has_more is False

    async def test_list_page_nominal(self, db_session):
        """list_page retourne les programs triés par (created_at, id)."""
        repo = SQLAlchemyProgramRepository(db_session)
        p1 = await repo.create(name="Program A", code="PA")
        p2 = await repo.create(name="Program B", code="PB")
        p3 = await repo.create(name="Program C", code="PC")

        page = await repo.list_page()

        assert len(page.items) == 3
        expected = sorted([p1, p2, p3], key=lambda p: (p.created_at, p.id))
        assert [p.id for p in page.items] == [p.id for p in expected]
        assert page.has_more is False
        assert page.next_cursor is None

    async def test_list_page_pagination_has_more(self, db_session):
        """list_page avec limit < total : has_more=True et next_cursor est défini."""
        repo = SQLAlchemyProgramRepository(db_session)
        for i in range(5):
            await repo.create(name=f"Prog Pagination {i}", code=f"PP{i}")

        page = await repo.list_page(limit=2)

        assert len(page.items) == 2
        assert page.has_more is True
        assert page.next_cursor is not None

    async def test_list_page_pagination_next_page(self, db_session):
        """list_page avec curseur : la deuxième page retourne les éléments suivants."""
        repo = SQLAlchemyProgramRepository(db_session)
        created = []
        for i in range(5):
            p = await repo.create(name=f"Prog Cursor {i}", code=f"PC{i}")
            created.append(p)

        first_page = await repo.list_page(limit=2)
        assert first_page.has_more is True
        assert len(first_page.items) == 2

        second_page = await repo.list_page(cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        # Vérifie qu'on ne retourne pas les mêmes éléments
        assert second_page.items[0].id != first_page.items[0].id
        assert second_page.items[0].id != first_page.items[1].id

    async def test_list_page_pagination_last_page(self, db_session):
        """list_page : la dernière page a has_more=False et next_cursor=None."""
        repo = SQLAlchemyProgramRepository(db_session)
        for i in range(3):
            await repo.create(name=f"Prog Last {i}", code=f"PL{i}")

        first_page = await repo.list_page(limit=2)
        assert first_page.has_more is True

        second_page = await repo.list_page(cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 1
        assert second_page.has_more is False
        assert second_page.next_cursor is None

    async def test_list_page_default_limit(self, db_session):
        """list_page utilise DEFAULT_PAGE_SIZE par défaut."""
        repo = SQLAlchemyProgramRepository(db_session)
        await repo.create(name="Single", code="SGL")

        page = await repo.list_page()

        assert len(page.items) == 1
        assert page.has_more is False


@pytest.mark.anyio
class TestProgramRepositoryUpdate:
    """Tests de la méthode update()."""

    async def test_update_nominal(self, db_session):
        """update modifie name et code du program existant."""
        repo = SQLAlchemyProgramRepository(db_session)
        created = await repo.create(name="Old Name", code="OLD")

        updated = await repo.update(created.id, name="New Name", code="NEW")

        assert updated is not None
        assert updated.id == created.id
        assert updated.name == "New Name"
        assert updated.code == "NEW"

    async def test_update_not_found_returns_none(self, db_session):
        """update sur un ID inexistant retourne None."""
        repo = SQLAlchemyProgramRepository(db_session)
        random_id = uuid.uuid4()

        result = await repo.update(random_id, name="Ghost", code="GHOST")

        assert result is None


@pytest.mark.anyio
class TestProgramRepositoryDelete:
    """Tests de la méthode delete()."""

    async def test_delete_nominal(self, db_session):
        """delete supprime le program et retourne True."""
        repo = SQLAlchemyProgramRepository(db_session)
        created = await repo.create(name="To Delete", code="DEL")

        result = await repo.delete(created.id)

        assert result is True
        # Vérifie que le program n'existe plus
        found = await repo.get_by_id(created.id)
        assert found is None

    async def test_delete_not_found_returns_false(self, db_session):
        """delete sur un ID inexistant retourne False."""
        repo = SQLAlchemyProgramRepository(db_session)
        random_id = uuid.uuid4()

        result = await repo.delete(random_id)

        assert result is False
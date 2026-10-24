"""
Pagination par curseur, partagée par TOUS les repositories du projet.

Le curseur encode (created_at, id) de la dernière ligne vue — stable même
si de nouvelles lignes sont insérées entre deux pages (contrairement à
offset/limit, qui peut sauter ou dupliquer des lignes si la table change
pendant la pagination). Le tri (created_at, id) donne un ordre TOTAL
même si plusieurs lignes partagent le même created_at à la milliseconde
près (id sert de départage).

Usage dans un repository :
    query = select(Group).order_by(Group.created_at, Group.id)
    if cursor:
        after_created_at, after_id = decode_cursor(cursor)
        query = query.where(
            tuple_(Group.created_at, Group.id) > (after_created_at, after_id)
        )
    query = query.limit(limit + 1)  # +1 pour savoir s'il y a une page suivante
    rows = (await session.execute(query)).scalars().all()
    return build_cursor_page(rows, limit)
"""
import base64
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass
class CursorPage(Generic[T]):
    items: list[T]
    next_cursor: str | None
    has_more: bool


def encode_cursor(created_at: datetime, entity_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{entity_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at_str, id_str = raw.split("|")
        return datetime.fromisoformat(created_at_str), uuid.UUID(id_str)
    except (ValueError, base64.binascii.Error) as e:
        raise ValueError("Curseur de pagination invalide") from e


def build_cursor_page(
    rows: list[T], limit: int, get_created_at_and_id
) -> CursorPage[T]:
    """
    `rows` doit contenir jusqu'à limit+1 lignes (convention : le
    repository sur-fetch d'une ligne pour détecter s'il y a une page
    suivante, sans avoir à faire un COUNT séparé — un aller-retour DB
    en moins).
    `get_created_at_and_id` : callable(row) -> (datetime, uuid.UUID),
    car chaque modèle expose ces champs différemment (nommage identique
    ici en pratique, mais reste explicite plutôt que d'halluciner un
    attribut générique .created_at/.id sur un TypeVar non contraint).
    """
    has_more = len(rows) > limit
    page_items = rows[:limit]
    next_cursor = None
    if has_more and page_items:
        created_at, entity_id = get_created_at_and_id(page_items[-1])
        next_cursor = encode_cursor(created_at, entity_id)
    return CursorPage(items=page_items, next_cursor=next_cursor, has_more=has_more)
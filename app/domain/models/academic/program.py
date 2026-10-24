"""
Program = la filière (ex: "Génie Civil", "Informatique").
Racine de la hiérarchie académique : Program -> Module / Group.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class Program(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "programs"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
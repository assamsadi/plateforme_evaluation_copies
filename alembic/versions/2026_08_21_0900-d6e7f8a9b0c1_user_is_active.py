"""
Migration — User.is_active pour la gestion admin des comptes (désactivation).

Colonne sur `users` (base de l'héritage Joined Table Inheritance
User -> Student/Professor/Admin), pas sur une table enfant : la
désactivation doit s'appliquer uniformément à N'IMPORTE quel rôle, jamais
seulement Student (Student.academic_status existe déjà mais est scopé
Student, sémantique différente — statut académique, pas autorisation
d'authentification, cf. docstring StatisticsService/UserService).

server_default="true" nécessaire le temps de l'ADD COLUMN NOT NULL sur une
table déjà peuplée (comptes existants) — retiré juste après, le défaut
Python (default=True sur le modèle) suffit pour tout nouvel enregistrement,
même convention que jobs.llm_call_count (cf. 5db7055178a7_job_llm_call_count).

Révision : 2026_08_21_0900-d6e7f8a9b0c1_user_is_active
Révision précédente : c5d6e7f8a9b0
"""
import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.alter_column("users", "is_active", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "is_active")

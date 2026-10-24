"""
Audit "ids manquants" (2026-09-06) : plusieurs tables n'avaient aucun
identifiant lisible pour un humain — seulement l'UUID technique — alors que
students (student_number) et professors (employee_number) en ont déjà un.
Ajoute un identifiant séquentiel entier, lisible et stable, aux 8 tables
concernées : admins, courses, exercises, submissions, questions,
evaluations, grade_appeals, submission_incidents.

Une séquence Postgres dédiée par table (jamais un COUNT(*)+1 applicatif —
même risque de course que get_next_attempt_number aurait sans son verrou,
cf. submission_repository.py) ; ADD COLUMN ... DEFAULT nextval(...) recadre
automatiquement les lignes existantes (une valeur par ligne, dans l'ordre
naturel du scan) — pas d'UPDATE manuel nécessaire. La colonne reste
NOT NULL + UNIQUE dès sa création, jamais un état intermédiaire nullable.

question_number est GLOBAL (toutes questions, tous exercices confondus) —
distinct de Question.order, qui reste la position DANS son exercice.

Revision ID: e0f1a2b3c4d5
Revises: d9e8f7c6b5a4
Create Date: 2026-09-06 14:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e8f7c6b5a4"
branch_labels = None
depends_on = None

_TABLES_AND_COLUMNS = [
    ("admins", "admin_number", "admin_number_seq"),
    ("courses", "course_number", "course_number_seq"),
    ("exercises", "exercise_number", "exercise_number_seq"),
    ("submissions", "submission_number", "submission_number_seq"),
    ("questions", "question_number", "question_number_seq"),
    ("evaluations", "evaluation_number", "evaluation_number_seq"),
    ("grade_appeals", "appeal_number", "appeal_number_seq"),
    ("submission_incidents", "incident_number", "incident_number_seq"),
]


def upgrade() -> None:
    for table_name, column_name, sequence_name in _TABLES_AND_COLUMNS:
        op.execute(f"CREATE SEQUENCE {sequence_name}")
        op.add_column(
            table_name,
            sa.Column(
                column_name,
                sa.Integer(),
                server_default=sa.text(f"nextval('{sequence_name}')"),
                nullable=False,
            ),
        )
        op.create_unique_constraint(f"uq_{table_name}_{column_name}", table_name, [column_name])
        # La séquence appartient à sa colonne (OWNED BY) — supprimer la
        # colonne plus tard supprimerait alors aussi la séquence
        # automatiquement, jamais orpheline.
        op.execute(f"ALTER SEQUENCE {sequence_name} OWNED BY {table_name}.{column_name}")


def downgrade() -> None:
    for table_name, column_name, sequence_name in _TABLES_AND_COLUMNS:
        op.drop_constraint(f"uq_{table_name}_{column_name}", table_name, type_="unique")
        op.drop_column(table_name, column_name)
        # La séquence a déjà été supprimée avec la colonne (OWNED BY,
        # cf. upgrade()) — DROP SEQUENCE IF EXISTS défensif uniquement.
        op.execute(f"DROP SEQUENCE IF EXISTS {sequence_name}")

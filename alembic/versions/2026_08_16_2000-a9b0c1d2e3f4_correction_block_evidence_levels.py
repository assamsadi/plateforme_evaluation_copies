"""
Migration — ajoute INFERRED_SINGLE_QUESTION et CONTENT_MATCHED à l'enum
Postgres block_evidence_level (cf. BlockEvidenceLevel,
app/domain/models/assessment/teacher_correction_block.py).

Avant cette migration, Document_Structuring_Agent ne pouvait exprimer que
LABEL_EXPLICITE (label textuel présent) ou UNRESOLVED_NO_LABEL (aucune
décision possible, bloquant pour la publication) — un bloc de correction
rattaché SANS label explicite (question unique dans la section, ou
correspondance de contenu via LLM parmi plusieurs questions candidates)
était donc faussement étiqueté LABEL_EXPLICITE dans le rapport. Ces 2
nouvelles valeurs distinguent la confiance réelle du rattachement sans
changer le comportement bloquant : seul UNRESOLVED_NO_LABEL reste filtré
par teacher_correction_block_repository.list_unresolved_by_exercise
(complétude bloquante pour la publication, cf. exercise_service.publish()) —
LABEL_EXPLICITE, INFERRED_SINGLE_QUESTION et CONTENT_MATCHED sont tous les
trois des blocs déjà résolus (question_id renseigné), jamais bloquants.

ALTER TYPE ADD VALUE (PG >= 12) au lieu de recréer le type : conserve les
lignes déjà en base pour les 2 valeurs existantes, jamais de perte de données
(même motif que la migration f8a9b0c1d2e3, add_ollama_provider).

Révision : 2026_08_16_2000-a9b0c1d2e3f4_correction_block_evidence_levels
Révision précédente : f8a9b0c1d2e3
"""
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE ne peut pas s'exécuter dans le même bloc de
    # transaction implicite qu'un DDL/DML qui l'utiliserait ensuite (PG) —
    # sans effet ici (migration atomique, valeurs ajoutées puis jamais
    # utilisées dans la même migration), mais AUTOCOMMIT évite toute
    # ambiguïté avec le mode transactionnel par défaut d'Alembic.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE block_evidence_level ADD VALUE IF NOT EXISTS 'inferred_single_question'")
        op.execute("ALTER TYPE block_evidence_level ADD VALUE IF NOT EXISTS 'content_matched'")


def downgrade() -> None:
    # PostgreSQL ne supporte pas DROP VALUE sur un type ENUM — recréer le
    # type impliquerait de vérifier/migrer d'éventuelles lignes utilisant
    # ces 2 valeurs au préalable, hors mandat d'une downgrade automatique
    # (décision actée : downgrade no-op, cohérent avec le risque d'un DROP
    # TYPE destructif sur une colonne activement utilisée — même motif que
    # la migration f8a9b0c1d2e3).
    pass

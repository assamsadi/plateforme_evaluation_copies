"""
Migration : suppression d'une SolutionVariant en 500 (test réel — bouton
"Supprimer" de Voir les variantes) — les FK enfants de reasoning_steps/
reasoning_step_dependencies/reasoning_clarification_requests vers
solution_variants/reasoning_steps n'avaient AUCUN ondelete (défaut Postgres
NO ACTION) alors que solution_variant_repository.py documente déjà
SolutionVariant comme racine d'agrégat couvrant ces 3 tables. Toute
variante ayant au moins une ReasoningStep (donc toute variante IA générée
avec succès) faisait échouer session.delete(variant) avec une
ForeignKeyViolation -> IntegrityError -> 500 non catché.

5 contraintes touchées :
  - reasoning_steps.variant_id -> solution_variants.id : ON DELETE CASCADE
    (les étapes n'ont aucun sens sans leur variante).
  - reasoning_steps.superseded_by -> reasoning_steps.id (auto-référence,
    versionnement Reasoning_Graph_Agent) : ON DELETE SET NULL — la
    suppression d'une étape qui en a superséded une autre ne doit jamais
    entraîner la suppression en cascade de l'étape supersédée elle-même
    (nullable déjà en base, aucune perte de contrainte NOT NULL).
  - reasoning_step_dependencies.step_id / .depends_on_step_id ->
    reasoning_steps.id : ON DELETE CASCADE (une arête du graphe n'a aucun
    sens sans les deux étapes qu'elle relie, cf. docstring du modèle
    "elle vit et meurt avec les étapes qu'elle relie").
  - reasoning_clarification_requests.variant_id -> solution_variants.id :
    ON DELETE CASCADE (même raisonnement que reasoning_steps.variant_id).
  - reasoning_clarification_requests.resulting_step_id -> reasoning_steps.id :
    ON DELETE SET NULL (nullable déjà en base — une demande de clarification
    garde son historique même si l'étape qu'elle a produite est ensuite
    supersédée/supprimée indépendamment de la variante).

Révision : 2026_08_28_2100-e9b926daabe8_reasoning_graph_cascade_delete
Révision précédente : 8281b93b9641
"""
from alembic import op

revision = "e9b926daabe8"
down_revision = "8281b93b9641"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("reasoning_steps_variant_id_fkey", "reasoning_steps", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_steps_variant_id_fkey", "reasoning_steps", "solution_variants",
        ["variant_id"], ["id"], ondelete="CASCADE",
    )

    op.drop_constraint("reasoning_steps_superseded_by_fkey", "reasoning_steps", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_steps_superseded_by_fkey", "reasoning_steps", "reasoning_steps",
        ["superseded_by"], ["id"], ondelete="SET NULL",
    )

    op.drop_constraint("reasoning_step_dependencies_step_id_fkey", "reasoning_step_dependencies", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_step_dependencies_step_id_fkey", "reasoning_step_dependencies", "reasoning_steps",
        ["step_id"], ["id"], ondelete="CASCADE",
    )

    op.drop_constraint("reasoning_step_dependencies_depends_on_step_id_fkey", "reasoning_step_dependencies", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_step_dependencies_depends_on_step_id_fkey", "reasoning_step_dependencies", "reasoning_steps",
        ["depends_on_step_id"], ["id"], ondelete="CASCADE",
    )

    op.drop_constraint("reasoning_clarification_requests_variant_id_fkey", "reasoning_clarification_requests", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_clarification_requests_variant_id_fkey", "reasoning_clarification_requests", "solution_variants",
        ["variant_id"], ["id"], ondelete="CASCADE",
    )

    op.drop_constraint("reasoning_clarification_requests_resulting_step_id_fkey", "reasoning_clarification_requests", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_clarification_requests_resulting_step_id_fkey", "reasoning_clarification_requests", "reasoning_steps",
        ["resulting_step_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("reasoning_clarification_requests_resulting_step_id_fkey", "reasoning_clarification_requests", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_clarification_requests_resulting_step_id_fkey", "reasoning_clarification_requests", "reasoning_steps",
        ["resulting_step_id"], ["id"],
    )

    op.drop_constraint("reasoning_clarification_requests_variant_id_fkey", "reasoning_clarification_requests", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_clarification_requests_variant_id_fkey", "reasoning_clarification_requests", "solution_variants",
        ["variant_id"], ["id"],
    )

    op.drop_constraint("reasoning_step_dependencies_depends_on_step_id_fkey", "reasoning_step_dependencies", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_step_dependencies_depends_on_step_id_fkey", "reasoning_step_dependencies", "reasoning_steps",
        ["depends_on_step_id"], ["id"],
    )

    op.drop_constraint("reasoning_step_dependencies_step_id_fkey", "reasoning_step_dependencies", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_step_dependencies_step_id_fkey", "reasoning_step_dependencies", "reasoning_steps",
        ["step_id"], ["id"],
    )

    op.drop_constraint("reasoning_steps_superseded_by_fkey", "reasoning_steps", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_steps_superseded_by_fkey", "reasoning_steps", "reasoning_steps",
        ["superseded_by"], ["id"],
    )

    op.drop_constraint("reasoning_steps_variant_id_fkey", "reasoning_steps", type_="foreignkey")
    op.create_foreign_key(
        "reasoning_steps_variant_id_fkey", "reasoning_steps", "solution_variants",
        ["variant_id"], ["id"],
    )

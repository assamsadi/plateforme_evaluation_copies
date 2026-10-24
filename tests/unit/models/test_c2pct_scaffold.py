"""
Tests unitaires pour le module de référence c2pct_scaffold.py.

Couvre :
- Les 7 compétences sont présentes, aucune manquante.
- Total exact de 15 sous-questions (répartition inégale assumée : 5/2/2/1/1/2/2).
- Chaque id de sous-question est unique sur l'ensemble des 15.
- Accesseurs (get_all_subquestions, get_subquestions_for, find_subquestion_by_id,
  get_competency_for_subquestion — Phase 4/4).
"""
from app.domain.models.competency.c2pct_scaffold import (
    C2PCT_SCAFFOLD,
    C2PCTSubQuestion,
    find_subquestion_by_id,
    get_all_subquestions,
    get_competency_for_subquestion,
    get_subquestions_for,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode


class TestScaffoldStructure:
    def test_all_seven_competencies_present(self):
        assert set(C2PCT_SCAFFOLD.keys()) == set(C2PCTSkillCode)

    def test_total_is_exactly_fifteen_subquestions(self):
        total = sum(len(subquestions) for subquestions in C2PCT_SCAFFOLD.values())
        assert total == 15

    def test_expected_distribution_per_competency(self):
        """Répartition inégale et délibérée du document source — pas un total théorique lissé."""
        expected_counts = {
            C2PCTSkillCode.DATA_AND_PLANNING: 5,
            C2PCTSkillCode.DECOMPOSITION_AND_ORGANIZATION: 2,
            C2PCTSkillCode.ALGORITHMIC_STRUCTURING: 2,
            C2PCTSkillCode.GENERALIZATION_AND_TRANSFER: 1,
            C2PCTSkillCode.SOLUTION_COMMUNICATION: 1,
            C2PCTSkillCode.SELF_EVALUATION_AND_CREATIVITY: 2,
            C2PCTSkillCode.REFLECTION_AND_METACOGNITION: 2,
        }
        actual_counts = {skill: len(subquestions) for skill, subquestions in C2PCT_SCAFFOLD.items()}
        assert actual_counts == expected_counts

    def test_no_competency_is_empty(self):
        for skill, subquestions in C2PCT_SCAFFOLD.items():
            assert len(subquestions) > 0, f"{skill} n'a aucune sous-question"

    def test_all_subquestion_ids_unique_across_all_competencies(self):
        all_ids = [sq.id for sq in get_all_subquestions()]
        assert len(all_ids) == len(set(all_ids)) == 15

    def test_subquestions_have_non_empty_label_and_reference_prompt(self):
        for sq in get_all_subquestions():
            assert sq.label.strip()
            assert sq.reference_prompt.strip()

    def test_subquestion_is_frozen(self):
        sq = get_all_subquestions()[0]
        try:
            sq.id = "mutated"
            mutated = True
        except Exception:
            mutated = False
        assert mutated is False


class TestGetAllSubquestions:
    def test_returns_flat_list_of_fifteen(self):
        result = get_all_subquestions()
        assert len(result) == 15
        assert all(isinstance(sq, C2PCTSubQuestion) for sq in result)


class TestGetSubquestionsFor:
    def test_returns_exact_subset_for_given_skill(self):
        result = get_subquestions_for(C2PCTSkillCode.GENERALIZATION_AND_TRANSFER)
        assert len(result) == 1
        assert result[0].id == "4"

    def test_returns_five_for_data_and_planning(self):
        result = get_subquestions_for(C2PCTSkillCode.DATA_AND_PLANNING)
        assert [sq.id for sq in result] == ["1.1", "1.2", "1.3", "1.4", "1.5"]


class TestFindSubquestionById:
    def test_finds_existing_id(self):
        sq = find_subquestion_by_id("3.2")
        assert sq is not None
        assert sq.label == "Représentation visuelle des étapes (schéma)"

    def test_returns_none_for_unknown_id(self):
        assert find_subquestion_by_id("99.9") is None

    def test_returns_none_for_partial_or_fuzzy_id_never_approximate_match(self):
        """Jamais une correspondance approchée — id exact ou rien."""
        assert find_subquestion_by_id("3") is None
        assert find_subquestion_by_id("3.20") is None


class TestGetCompetencyForSubquestion:
    def test_resolves_each_of_the_fifteen_ids_to_its_parent_competency(self):
        for skill, subquestions in C2PCT_SCAFFOLD.items():
            for sq in subquestions:
                assert get_competency_for_subquestion(sq.id) == skill

    def test_returns_none_for_unknown_id_never_guessed(self):
        assert get_competency_for_subquestion("99.9") is None

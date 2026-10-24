"""
Tests unitaires pour Recommendation_Agent — calcul pur déterministe, aucun
appel LLM, aucun accès DB (cf. docstring module) : les 3 paliers de
priorisation, la bande de relevance_score garantissant l'ordre entre
paliers, le matching fin/repli des exercices, et le repli de difficulté.

Aucun fichier de test n'existait pour cet agent avant ce ticket (vérifié
via Glob) — première couverture de sa logique de priorisation.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.Competency_Assessment_Agent import CompetencyProfileLine
from app.agents.Recommendation_Agent import ExerciseCompetencyCoverage, RecommendationAgent
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode

STUDENT_ID = uuid.uuid4()
MODULE_ID = uuid.uuid4()
NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)

WEAK_MASTERY_THRESHOLD = Decimal("60.0")
LOW_CONFIDENCE_THRESHOLD = Decimal("0.6")


def _line(
    competency: C2PCTSkillCode = C2PCTSkillCode.DATA_AND_PLANNING,
    mastery_level: str = "50.0",
    confidence_level: str = "0.8",
    is_persistent_weakness: bool = False,
    evaluations_count: int = 3,
    weaknesses: list[str] | None = None,
) -> CompetencyProfileLine:
    return CompetencyProfileLine(
        competency=competency,
        mastery_level=Decimal(mastery_level),
        trend="STABLE",
        evaluations_count=evaluations_count,
        confidence_level=Decimal(confidence_level),
        is_persistent_weakness=is_persistent_weakness,
        weaknesses=weaknesses or [],
    )


def _exercise(
    competency: C2PCTSkillCode = C2PCTSkillCode.DATA_AND_PLANNING,
    covered_subquestions: frozenset[str] = frozenset(),
    difficulty_level: str | None = "facile",
    title: str = "Exercice",
) -> ExerciseCompetencyCoverage:
    return ExerciseCompetencyCoverage(
        exercise_id=uuid.uuid4(),
        exercise_title=title,
        competencies=frozenset({competency}),
        covered_subquestions=covered_subquestions,
        difficulty_level=difficulty_level,
    )


def _generate(lines, coverage, **overrides):
    kwargs = dict(
        student_id=STUDENT_ID, module_id=MODULE_ID,
        competency_lines=lines, library_coverage=coverage, generated_at=NOW,
        weak_mastery_threshold=WEAK_MASTERY_THRESHOLD,
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
        max_per_competency=2, max_total=10,
    )
    kwargs.update(overrides)
    return RecommendationAgent.generate(**kwargs)


def test_persistent_weakness_gets_tier3_remediation_and_facile_difficulty():
    line = _line(mastery_level="30.0", is_persistent_weakness=True)
    coverage = [_exercise(difficulty_level="facile")]
    result = _generate([line], coverage)
    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.category == "remediation"
    assert "persistante" in rec.reason


def test_low_mastery_not_persistent_gets_tier2_remediation():
    line = _line(mastery_level="40.0", is_persistent_weakness=False)
    coverage = [_exercise(difficulty_level="intermediaire")]
    result = _generate([line], coverage)
    assert len(result.recommendations) == 1
    assert result.recommendations[0].category == "remediation"


def test_high_mastery_low_confidence_gets_tier1_verification():
    line = _line(mastery_level="90.0", confidence_level="0.3", is_persistent_weakness=False)
    coverage = [_exercise(difficulty_level="avance")]
    result = _generate([line], coverage)
    assert len(result.recommendations) == 1
    assert result.recommendations[0].category == "verification"


def test_high_mastery_high_confidence_gets_no_recommendation():
    """Mastery haut ET confiance haute -> rien à recommander, jamais forcé."""
    line = _line(mastery_level="90.0", confidence_level="0.9", is_persistent_weakness=False)
    coverage = [_exercise()]
    result = _generate([line], coverage)
    assert result.recommendations == []


def test_relevance_score_ordering_across_tiers_holds_regardless_of_gap():
    """
    Tier 3 (persistant) > tier 2 (faiblesse ponctuelle) > tier 1
    (vérification) DOIT tenir même quand l'écart dans le palier bas est
    énorme et l'écart dans le palier haut est minuscule (cf. bande [0,1]
    par palier, docstring module).
    """
    tier3_barely_below_threshold = _line(
        competency=C2PCTSkillCode.DATA_AND_PLANNING,
        mastery_level="59.9", is_persistent_weakness=True,  # gap minuscule dans tier 3
    )
    tier1_very_low_confidence = _line(
        competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING,
        mastery_level="95.0", confidence_level="0.01",  # gap énorme dans tier 1
    )
    coverage = [
        _exercise(competency=C2PCTSkillCode.DATA_AND_PLANNING, title="Ex A"),
        _exercise(competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING, title="Ex B"),
    ]
    result = _generate([tier3_barely_below_threshold, tier1_very_low_confidence], coverage)
    assert len(result.recommendations) == 2
    # Trié par relevance_score décroissant -> tier 3 doit rester premier.
    assert result.recommendations[0].category == "remediation"
    assert result.recommendations[0].exercise_title == "Ex A"
    assert result.recommendations[0].relevance_score > result.recommendations[1].relevance_score


def test_fine_matching_prefers_exercise_covering_weak_subquestion():
    line = _line(mastery_level="40.0", weaknesses=["1.1 (Lister et catégoriser les données)"])
    fine_match = _exercise(covered_subquestions=frozenset({"1.1"}), title="Ex fine")
    broad_match = _exercise(covered_subquestions=frozenset({"1.5"}), title="Ex broad")
    result = _generate([line], [fine_match, broad_match])
    titles = {r.exercise_title for r in result.recommendations}
    assert titles == {"Ex fine"}  # jamais le broad match tant qu'un fine match existe


def test_fine_matching_falls_back_to_whole_competency_when_no_fine_match():
    """Bibliothèque trop pauvre pour la sous-question précise -> repli sur toute la compétence."""
    line = _line(mastery_level="40.0", weaknesses=["1.1 (Lister et catégoriser les données)"])
    broad_only = _exercise(covered_subquestions=frozenset({"1.5"}), title="Ex broad")
    result = _generate([line], [broad_only])
    assert [r.exercise_title for r in result.recommendations] == ["Ex broad"]


def test_difficulty_preference_falls_back_when_library_has_none_at_target():
    """tier 2 vise 'intermediaire' ; si la Library n'a que du 'avance' pour cette compétence, repli quand même."""
    line = _line(mastery_level="40.0")
    only_avance = _exercise(difficulty_level="avance", title="Ex avancé")
    result = _generate([line], [only_avance])
    assert [r.exercise_title for r in result.recommendations] == ["Ex avancé"]


def test_weak_subquestion_ids_strips_formatted_label():
    ids = RecommendationAgent._weak_subquestion_ids(
        _line(weaknesses=["1.1 (Lister et catégoriser les données)", "3.2 (Représentation visuelle)"])
    )
    assert ids == frozenset({"1.1", "3.2"})


def test_max_per_competency_and_max_total_respected():
    line = _line(mastery_level="30.0", is_persistent_weakness=True)
    coverage = [_exercise(title=f"Ex {i}") for i in range(5)]
    result = _generate([line], coverage, max_per_competency=2, max_total=10)
    assert len(result.recommendations) == 2  # plafonné par competency, malgré 5 candidats

    many_lines = [
        _line(competency=c, mastery_level="30.0", is_persistent_weakness=True)
        for c in list(C2PCTSkillCode)[:5]
    ]
    many_coverage = [_exercise(competency=c, title=f"Ex-{c.value}") for c in list(C2PCTSkillCode)[:5]]
    result_total = _generate(many_lines, many_coverage, max_per_competency=2, max_total=3)
    assert len(result_total.recommendations) == 3  # plafonné globalement
